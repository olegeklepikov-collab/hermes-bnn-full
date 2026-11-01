#!/usr/bin/env python3
"""BNN release engineering. Standard library only; no production writes or credentials."""
from __future__ import annotations
import argparse,datetime,gzip,hashlib,json,os,re,shutil,stat,subprocess,sys,tarfile,time,unicodedata
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
NAMESPACE='bnn-release-v1'


def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read(p):return json.loads(Path(p).read_text())


def write(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temporary=p.with_name(p.name+'.pending')
    with temporary.open('w') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,p)


def git(*args):return subprocess.run(['git',*args],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()


def clean_commit():
    if git('status','--porcelain','--untracked-files=all'):raise PermissionError('clean_committed_source_required')
    return git('rev-parse','HEAD')


def resources():
    r=read(ROOT.parent/'.operator/resources.json')
    for k in ['development_root','build_root','test_root','release_root','runtime_cache','production_read_only_root']:
        if not Path(r[k]).is_absolute():raise PermissionError('absolute_resource_path_required')
    return r


def confined(path,base):
    path=Path(path).resolve();base=Path(base).resolve()
    if path==base or not path.is_relative_to(base):raise PermissionError('new_child_path_required')
    return path


def object_entry(p):
    m=stat.S_IMODE(p.lstat().st_mode)
    if p.is_symlink():return {'type':'symlink','mode':m,'target':os.readlink(p)}
    if p.is_dir():return {'type':'directory','mode':m}
    if p.is_file():return {'type':'file','mode':m,'bytes':p.stat().st_size,'sha256':digest(p)}
    raise PermissionError('unsupported_filesystem_object')


def inventory(root):
    found={}
    for base,dirs,files in os.walk(root,followlinks=False):
        dirs.sort();files.sort()
        for name in dirs+files:
            p=Path(base)/name;n=unicodedata.normalize('NFC',str(p.relative_to(root)))
            if n=='bundle-manifest.json':continue
            if n in found:raise PermissionError('ambiguous_unicode_path')
            found[n]=object_entry(p)
    return found


def verify_tree(root,expected_manifest=None):
    m=Path(root)/'bundle-manifest.json'
    if expected_manifest and digest(m)!=expected_manifest:raise PermissionError('manifest_not_the_locked_artifact')
    original=read(m)['objects'];expected={unicodedata.normalize('NFC',k):v for k,v in original.items()}
    if len(expected)!=len(original):raise PermissionError('ambiguous_manifest_unicode_path')
    actual=inventory(root)
    if expected!=actual:
        changed=sorted(k for k in expected.keys()|actual.keys() if expected.get(k)!=actual.get(k))
        raise PermissionError('program_inventory_changed:'+repr(changed[:5]))
    return len(actual)


def safe_member(member,destination):
    # Preserve the declared modes, but reject all names/links escaping the one bundle.
    n=PurePosixPath(member.name)
    if n.is_absolute() or '..' in n.parts or not n.parts or n.parts[0]!='Hermes-BNN-Full':raise PermissionError('unsafe_archive_name')
    root=Path(destination).resolve()/'Hermes-BNN-Full';target=Path(destination).joinpath(*n.parts).resolve()
    if target!=root and not target.is_relative_to(root):raise PermissionError('archive_parent_escape')
    if member.issym() or member.islnk():
        link=PurePosixPath(member.linkname)
        if link.is_absolute():raise PermissionError('absolute_archive_link')
        resolved=(target.parent/str(link)).resolve() if member.issym() else Path(destination).joinpath(*link.parts).resolve()
        if resolved!=root and not resolved.is_relative_to(root):raise PermissionError('archive_link_escape')
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):raise PermissionError('archive_special_object')
    if member.mode & 0o7000:raise PermissionError('archive_privileged_mode')
    member.uid=member.gid=None;member.uname=member.gname=None
    return member


def unarchive(archive,destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('fresh_install_target_required')
    destination.mkdir(parents=True)
    with tarfile.open(archive,'r:gz') as t:t.extractall(destination,filter=safe_member)
    return destination/'Hermes-BNN-Full'


def sign_manifest(path,key):
    subprocess.run(['/usr/bin/ssh-keygen','-Y','sign','-f',str(key),'-n',NAMESPACE,str(path)],check=True,capture_output=True)


def verify_release(directory):
    directory=Path(directory).resolve();p=directory/'RELEASE.json'
    subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(ROOT/'trust/allowed_signers'),'-I','bnn-release','-n',NAMESPACE,'-s',str(p)+'.sig'],input=p.read_bytes(),check=True,capture_output=True)
    r=read(p);name=r['archive']['name']
    if Path(name).name!=name or not re.fullmatch(r'[A-Za-z0-9._-]+',name):raise PermissionError('unsafe_asset_name')
    if digest(directory/name)!=r['archive']['sha256']:raise PermissionError('archive_sha256_mismatch')
    return r


def normalized_tarinfo(info,epoch):
    info.uid=info.gid=0;info.uname=info.gname='';info.mtime=epoch
    info.pax_headers={}
    return info


def committed_product_files():
    return [ROOT/n for n in git('ls-files','-z','product').split('\0') if n.startswith('product/')]


def verify_dependencies(cache):
    expected={unicodedata.normalize('NFC',n):x for n,x in read(ROOT/'locks/runtime.objects.json').items()}
    source={unicodedata.normalize('NFC',n) for n in read(ROOT/'locks/source-import.json')['files']}
    source.update(unicodedata.normalize('NFC',str(p.relative_to(ROOT/'product'))) for p in committed_product_files())
    actual={n:x for n,x in inventory(cache).items() if n not in source and n!='BNN-PRODUCT.json'}
    if actual!=expected:
        changed=sorted(n for n in actual.keys()|expected.keys() if actual.get(n)!=expected.get(n))
        raise PermissionError('locked_dependency_content_changed:'+repr(changed[:5]))
    return len(actual)


def build(version):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',version):raise ValueError('invalid_product_version')
    commit=clean_commit();r=resources();lock=read(ROOT/'locks/product.lock.json');cache=Path(r['runtime_cache'])
    count=verify_dependencies(cache)
    build_id=version+'-g'+commit[:12];out=confined(Path(r['build_root'])/'candidates'/build_id,r['build_root'])
    if out.exists():raise FileExistsError('immutable_build_id_exists')
    if shutil.disk_usage(out.parent if out.parent.exists() else Path(r['build_root'])).free<9*1024**3:raise OSError('at_least_9_GiB_free_required_for_full_archive')
    out.mkdir(parents=True);bundle=out/'Hermes-BNN-Full'
    subprocess.run(['/bin/cp','-cRp',str(cache),str(bundle)],check=True)
    # Every imported source must remain represented. Deletions need an explicit recipe.
    sources=read(ROOT/'locks/source-import.json')['files']
    for n in sources:
        if not (ROOT/'product'/n).is_file():raise PermissionError('source_deletion_requires_declared_recipe:'+n)
    changed=[];src_inventory={}
    for p in sorted(committed_product_files()):
        if p.is_symlink():raise PermissionError('source_symlink_not_supported')
        if not p.is_file():continue
        n=str(p.relative_to(ROOT/'product'));target=bundle/n
        if not target.resolve().is_relative_to(bundle.resolve()):raise PermissionError('source_overlay_escape')
        target.parent.mkdir(parents=True,exist_ok=True);h=digest(p);mode=sources.get(n,{}).get('mode',0o755 if os.access(p,os.X_OK) else 0o644)
        if not target.is_file() or digest(target)!=h or stat.S_IMODE(target.stat().st_mode)!=mode:
            if target.is_symlink():raise PermissionError('cannot_overlay_runtime_link')
            shutil.copy2(p,target);target.chmod(mode);changed.append(n)
        src_inventory[n]={'sha256':h,'mode':mode}
    epoch=int(git('show','-s','--format=%ct',commit))
    product={'contract':'BNNIntegratedProductV1','version':version,'build_id':build_id,'source_commit':commit,'source_tree':git('rev-parse','HEAD^{tree}'),'source_date_epoch':epoch,'components':lock['components'],'runtime_manifest_sha256':lock['runtime']['manifest_sha256'],'owner_data_included':False,'credentials_included':False,'historical_patch_chain_required':False}
    write(bundle/'BNN-PRODUCT.json',product)
    meta=read(bundle/'bundle-manifest.json');meta.pop('required_context_fix',None);meta.pop('base_manifest_sha256',None);meta.update(product_release=version,source_commit=commit,objects=inventory(bundle))
    write(bundle/'bundle-manifest.json',meta)
    archive=out/f'Hermes-BNN-{build_id}-macos-arm64.tar.gz'
    def normalized(t):return normalized_tarinfo(t,epoch)
    with archive.open('xb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0,compresslevel=1) as gz,tarfile.open(fileobj=gz,mode='w|',format=tarfile.PAX_FORMAT) as tar:
        tar.add(bundle,arcname=bundle.name,recursive=False,filter=normalized)
        for base,dirs,files in os.walk(bundle,followlinks=False):
            dirs.sort();files.sort()
            for name in dirs+files:
                p=Path(base)/name;tar.add(p,arcname=bundle.name+'/'+str(p.relative_to(bundle)),recursive=False,filter=normalized)
    release={**product,'archive':{'name':archive.name,'bytes':archive.stat().st_size,'sha256':digest(archive)},'bundle_manifest_sha256':digest(bundle/'bundle-manifest.json'),'source_file_count':len(src_inventory),'cache_objects_verified':count,'changed_program_files_from_cache':changed,'source_projection_sha256':hashlib.sha256(json.dumps(src_inventory,sort_keys=True).encode()).hexdigest(),'qualification_status':'pending','external_model_execution_claimed':False}
    write(out/'RELEASE.json',release);sign_manifest(out/'RELEASE.json',Path(r['development_root'])/'.operator/keys/release_ed25519')
    write(out/'build-receipt.json',{'source_commit':commit,'release_manifest_sha256':digest(out/'RELEASE.json'),'archive_sha256':release['archive']['sha256'],'build_complete':True,'production_changed':False})
    print(json.dumps({'build':str(out),'build_id':build_id,'archive':release['archive']},ensure_ascii=False),flush=True)
    return out


def clean_environment(home):
    # Explicit allow-list: no cloud/Telegram/OAuth tokens from the caller environment.
    e={k:v for k,v in os.environ.items() if k in ['PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT']}
    e.update(HOME=str(home),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',COPYFILE_DISABLE='1',DO_NOT_TRACK='1')
    return e


def logged(command,env,cwd,log,timeout=600):
    with Path(log).open('w') as f:
        p=subprocess.run(list(map(str,command)),env=env,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if p.returncode:raise RuntimeError('native_step_failed:'+Path(log).name+':'+str(p.returncode))


def qualify(directory,environment):
    if environment not in ['test','development']:raise PermissionError('production_is_read_only_in_this_phase')
    r=resources();fallback=Path(r['test_root']) if environment=='test' else Path(r['development_root'])/'instances'
    base=Path(r.get('environment_roots',{}).get(environment,str(fallback)))
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=confined(base/stamp,base)
    if target.is_relative_to(Path(r['production_read_only_root']).resolve()):raise PermissionError('production_path_forbidden')
    home=ROOT.parent/'.operator/command-home';home.mkdir(exist_ok=True)
    subprocess.run([sys.executable,'-B',str(ROOT/'packaging/qualify_native.py'),'--source',str(ROOT),'--release',str(Path(directory).resolve()),'--target',str(target),'--environment',environment],env=clean_environment(home),check=True)
    return target


def admit(directory,evidence_files):
    from admission import evaluate
    release=verify_release(directory);r=resources();proofs=[]
    allowed=[Path(directory).resolve(),ROOT.resolve(),ROOT.parent/'.operator',Path(r['release_root']).resolve()]
    for name in evidence_files:
        path=Path(name).resolve()
        subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(ROOT/'trust/allowed_signers'),'-I','bnn-release','-n',NAMESPACE,'-s',str(path)+'.sig'],input=path.read_bytes(),check=True,capture_output=True)
        item=read(path)
        for gate in item.get('gates',{}).values():
            witness=Path(gate.get('witness_path','')).resolve()
            if not any(witness.is_relative_to(base) for base in allowed):raise PermissionError('witness_outside_approved_evidence_roots')
            if not witness.is_file() or digest(witness)!=gate.get('witness_sha256'):raise PermissionError('gate_witness_missing_or_changed')
        proofs.append(item)
    result=evaluate(read(ROOT/'docs/RELEASE_ACCEPTANCE.json')['required_gates'],release,proofs)
    result['operator_source_commit']=git('rev-parse','HEAD')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=Path(directory)/('ADMISSION-'+stamp+'.json');write(output,result)
    sign_manifest(output,Path(r['development_root'])/'.operator/keys/release_ed25519')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def status():
    r=resources();result={'source_commit':git('rev-parse','HEAD'),'source_clean':not bool(git('status','--porcelain')),'resources':{k:v for k,v in r.items() if k!='runtime_cache'},'production_writes_implemented':False,'candidates':[],'qualifications':[]}
    registry=ROOT.parent/'.operator/environments.json'
    result['native_environments']=read(registry) if registry.exists() else {}
    prod=Path(r['production_read_only_root'])
    result['production']={'root':str(prod),'layout':'legacy_not_migrated' if not (prod/'BNN-PRODUCT.json').exists() else 'versioned','write_authority':False}
    p=Path(r['build_root'])/'candidates'
    for d in sorted(p.glob('*/RELEASE.json')) if p.exists() else []:result['candidates'].append({'build_id':read(d)['build_id'],'manifest':str(d)})
    for d in sorted(Path(r['test_root']).glob('*/qualification.json')):result['qualifications'].append({'path':str(d),'complete':read(d)['complete'],'production_promotable':read(d)['production_promotable']})
    print(json.dumps(result,ensure_ascii=False,indent=2))


def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    s.add_parser('status');x=s.add_parser('admit');x.add_argument('directory',type=Path);x.add_argument('--evidence',nargs='+',type=Path,required=True)
    x=s.add_parser('build');x.add_argument('--version',required=True)
    x=s.add_parser('verify');x.add_argument('directory',type=Path)
    x=s.add_parser('qualify');x.add_argument('directory',type=Path);x.add_argument('--environment',choices=['test','development'],default='test')
    a=p.parse_args()
    if a.action=='status':status()
    elif a.action=='build':build(a.version)
    elif a.action=='admit':
        result=admit(a.directory,a.evidence)
        if not result['eligible_for_production']:raise SystemExit(3)
    elif a.action=='verify':print(json.dumps(verify_release(a.directory),ensure_ascii=False,indent=2))
    elif a.action=='qualify':qualify(a.directory,a.environment)


if __name__=='__main__':main()
