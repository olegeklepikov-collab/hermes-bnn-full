"""Rebuild the owned Intake wheel offline from declared source and exact native pins."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path
import release_cli as release
from pair_contract import verify_pins,verify_runtime_origin

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--python',type=Path,required=True)
    parser.add_argument('--epoch',type=int);parser.add_argument('--check-reproducible',action='store_true');a=parser.parse_args()
    root=release.ROOT;base=root/'product/Intake';lock=release.read(root/'locks/product.lock.json');version=lock['components']['Intake']
    contract=release.read(base/'src/bnn_intake/data/native-compatibility.json')
    if contract['memory_version']!=lock['components']['Memory']:raise PermissionError('qualified_pair_required')
    memory=root/'product/Hermes/Memory/releases'/contract['memory_version']
    verify_pins(memory,root/'product/Hermes/hermes-agent',contract)
    verify_runtime_origin(release.read(memory/'compute-runtime.json'),release.read(memory/'parser-runtime.json'))
    epoch=a.epoch if a.epoch is not None else int(release.git('show','-s','--format=%ct','HEAD'))
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work=base/'.test-state'/('wheel-'+stamp);work.mkdir(parents=True)
    env=release.clean_environment(work);env['SOURCE_DATE_EPOCH']=str(epoch)
    wheels=[]
    for index in range(2 if a.check_reproducible else 1):
        stage=work/str(index);stage.mkdir();shutil.copytree(base/'src',stage/'src');shutil.copy2(base/'pyproject.toml',stage/'pyproject.toml')
        output=stage/'dist'
        with (stage/'build.log').open('w') as log:
            # Preserve the venv entry path; resolving its symlink loses pyvenv.cfg.
            subprocess.run([str(a.python.absolute()),'-B','-c','import setuptools.build_meta as b;b.build_wheel('+repr(str(output))+')'],cwd=stage,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        wheels.append(output/f'hermes_bnn_intake-{version}-py3-none-any.whl')
    if len(wheels)==2 and release.digest(wheels[0])!=release.digest(wheels[1]):raise PermissionError('intake_wheel_not_reproducible')
    packages=base/'packages';packages.mkdir(exist_ok=True);wheel=packages/wheels[0].name
    shutil.copy2(wheels[0],wheel)
    with zipfile.ZipFile(wheel) as archive:members={n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
    release.write(packages/'manifest.json',{'contract':'BNNIntakeDistributionV1','version':version,'wheel':wheel.name,'wheel_sha256':release.digest(wheel),'members_sha256':members,'build':{'backend':'setuptools.build_meta','SOURCE_DATE_EPOCH':epoch,'network_used':False,'two_builds_identical':len(wheels)==2,'pyproject_sha256':release.digest(base/'pyproject.toml')}})
    payload=release.read(base/'PACKAGE-MANIFEST.json');payload['version']=version;cache=Path(release.resources()['runtime_cache'])/'Intake'
    dependencies=release.read(root/'locks/runtime.objects.json')
    for name in payload['files']:
        source=base/name
        if not source.is_file():
            source=cache/name;expected=dependencies['Intake/'+name]['sha256']
            if release.digest(source)!=expected:raise PermissionError('unqualified_cached_payload:'+name)
        payload['files'][name]=release.digest(source)
    release.write(base/'PACKAGE-MANIFEST.json',payload)
    (base/'PAYLOAD-SHA256SUMS').write_text(''.join(f'{h}  {n}\n' for n,h in sorted(payload['files'].items())))
    names=['PACKAGE-MANIFEST.json','PAYLOAD-SHA256SUMS','packages/manifest.json','packages/'+wheel.name]
    (base/'SHA256SUMS').write_text(''.join(release.digest(base/n)+'  '+n+'\n' for n in names))
    print(json.dumps({'wheel':str(wheel),'sha256':release.digest(wheel),'two_builds_identical':len(wheels)==2,'network_used':False}))

if __name__=='__main__':main()
