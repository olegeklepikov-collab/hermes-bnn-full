"""Install a neutral service overlay into an already initialized own BNN base."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys

def digest(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600)
def replace(value,root):
 if isinstance(value,str):return value.replace('__HERMES_ROOT__',str(root)).replace('__USER_HOME__',str(Path.home()))
 if isinstance(value,list):return [replace(v,root) for v in value]
 if isinstance(value,dict):return {replace(k,root):replace(v,root) for k,v in value.items()}
 return value

def install(overlay,root):
 overlay=overlay.resolve();root=root.resolve()
 manifest=json.loads((overlay/'manifest.json').read_text())
 for name,row in manifest['files'].items():
  p=overlay/name
  if p.is_symlink():
   if row!={'symlink':os.readlink(p)}:raise PermissionError('overlay_link_changed')
  elif not p.is_file() or digest(p)!=row.get('sha256'):raise PermissionError('overlay_file_changed:'+name)
 cfg=json.loads((root/'Memory/settings.json').read_text())
 if cfg.get('service_integration') or (root/'Services').exists():raise FileExistsError('Existing service integration must be upgraded separately; never overwrite owner state')
 if Path(cfg['package_root']).name!='2.0.0-dev.30':raise PermissionError('This overlay requires the documented pristine dev30 base')
 if not (root/'state/bootstrap.json').exists():raise PermissionError('Initialize the neutral base before applying this overlay')
 if not Path('/Library/Frameworks/R.framework/Resources/bin/exec/R').is_file():raise FileNotFoundError('Install the supplied official native arm64 R release first')
 # Overlay contains programs/dependencies only; no personal database is replaced.
 for path in (overlay/'payload').rglob('*'):
  rel=path.relative_to(overlay/'payload');target=root/rel
  if path.is_dir() and not path.is_symlink():target.mkdir(parents=True,exist_ok=True);continue
  target.parent.mkdir(parents=True,exist_ok=True)
  if path.is_symlink():
   link=os.readlink(path).replace('__HERMES_ROOT__',str(root))
   if target.exists() or target.is_symlink():raise FileExistsError('Refusing existing program link:'+str(rel))
   target.symlink_to(link)
  else:
   if path.stat().st_size>=32*1024*1024:
    copied=subprocess.run(['/bin/cp','-c',str(path),str(target)],capture_output=True)
    if copied.returncode:shutil.copyfile(path,target)
    shutil.copymode(path,target);continue
   raw=path.read_bytes()
   if b'\0' not in raw[:8192]:
    try:raw=raw.decode().replace('__HERMES_ROOT__',str(root)).replace('__USER_HOME__',str(Path.home())).encode()
    except UnicodeDecodeError:pass
   target.write_bytes(raw);target.chmod(path.stat().st_mode&0o777)
 for file in (root/'ASReview/runtime').rglob('*'):
  if file.is_file() and not file.is_symlink() and file.stat().st_size<1024*1024 and file.name in {'pyvenv.cfg','python._pth'}:
   file.write_text(file.read_text().replace('__HERMES_ROOT__',str(root)))
 reg=replace(json.loads((overlay/'registry.template.json').read_text()),root)
 authority=root/'state/authority/services';authority.mkdir(parents=True,mode=0o700,exist_ok=True);authority.chmod(0o700)
 for entry in reg['services']:
  save(entry['authority_file'],{'headers':{},'env':{}})
  state=Path(entry['state_root'])
  for name in ['config','checks','exports','cache','projects','documents','logs','stream-results','imports','data','downloads','content','results']:(state/name).mkdir(parents=True,exist_ok=True)
 # Own local Zotero authorization is provided by the initialized base, never the source owner.
 z=Path(cfg['zotero_root']);target=root/'Services/software/Zotero/config'
 if (z/'identity.json').exists():
  identity=json.loads((z/'identity.json').read_text());identity.update(output_root=str(target.parent/'exports'),import_roots=list(cfg['projects'].values()))
  save(target/'identity.json',identity)
 if (z/'authorization.json').exists():save(target/'authorization.json',json.loads((z/'authorization.json').read_text()))
 save(root/'Services/registry.private.json',reg)
 # Preserve this owner's base bindings and all five mandatory controllers.
 env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','TMPDIR','LANG','LC_ALL'}}
 env.update(HERMES_HOME=str(root/'data'),HERMES_BNN_ROOT=str(root),HERMES_BN_ROOT=str(root),PYTHONPATH=str(root/'hermes-agent'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
 python=root/'hermes-agent/venv/bin/python'
 for operation in ['build','contracts']:
  result=subprocess.run([python,root/'Development/service_cli.py',operation],cwd=root,env=env,capture_output=True,text=True)
  (root/'Development/services-20261028'/('new-owner-'+operation+'.log')).write_text(result.stdout+result.stderr)
  if result.returncode:raise RuntimeError('Overlay '+operation+' failed; preserved base configuration is still active')
 # No automatic gateway, external API request, OAuth, purchase or credential migration.
 base=root/'Development/services-20261028';candidate=json.loads((base/'candidate-settings.private.json').read_text());profile=json.loads((base/'candidate-profile.private.json').read_text())
 save(root/'Memory/settings.json',candidate);save(root/'data/config.yaml',profile)
 if (root/'Development/instance.json').exists():
  instance=json.loads((root/'Development/instance.json').read_text());instance['memory_package']=candidate['package_root'];save(root/'Development/instance.json',instance)
 # BNN's ordinary R wrapper uses the same native library as service calls.
 r_env=root/'R/environment.sh'
 if r_env.exists():r_env.write_text(r_env.read_text().replace('$bnn_r_root/R/packages:', '$bnn_r_root/Services/software/R/framework-library:'))
 out={'installed':True,'connected':True,'external_credentials_migrated':False,'external_calls_performed':False,'provider_verified':False,'memory_package':Path(candidate['package_root']).name,'source_release':manifest['source_release'],'base_previous_settings':str(base/'before-settings.private.json')}
 save(base/'new-owner-installed.json',out);return out

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--overlay',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(install(a.overlay,a.root),ensure_ascii=False,indent=2))
