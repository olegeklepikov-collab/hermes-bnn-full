"""Space-efficient archive qualification on APFS: full stream verification + independent clone.
No provider credentials or production state. This is a native operator adapter, not model testing.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,tarfile,unicodedata,datetime


def register_qualification(registry,environment,entry):
 result=dict(registry)
 candidates=dict(result.get('_qualified_candidates',{}));candidates[environment]=entry
 result['_qualified_candidates']=candidates
 # Fresh qualification must not silently replace an existing persistent profile.
 if environment not in result:result[environment]=entry
 return result


def main():
 a=argparse.ArgumentParser();a.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);a.add_argument('--release',type=Path,required=True);a.add_argument('--target',type=Path,required=True);a.add_argument('--environment',choices=['development','test'],required=True);a=a.parse_args()
 spec=importlib.util.spec_from_file_location('bnn_release',a.source/'packaging/release_cli.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 release=m.verify_release(a.release);bundle=a.release/'Hermes-BNN-Full';manifest=bundle/'bundle-manifest.json'
 if m.digest(manifest)!=release['bundle_manifest_sha256']:raise PermissionError('materialized_manifest_not_the_signed_release')
 expected={unicodedata.normalize('NFC',n):x for n,x in m.read(manifest)['objects'].items()}
 verified=a.release/'ARCHIVE-READBACK.json'
 if not verified.exists():
  actual={};prefix='Hermes-BNN-Full/'
  with tarfile.open(a.release/release['archive']['name'],'r|gz') as tar:
   for row in tar:
    if row.name=='Hermes-BNN-Full':continue
    if not row.name.startswith(prefix):raise PermissionError('unexpected_archive_root')
    name=unicodedata.normalize('NFC',row.name[len(prefix):])
    if name in actual:raise PermissionError('duplicate_archive_member')
    entry={'mode':row.mode&0o7777}
    if row.isfile():
     f=tar.extractfile(row);h=hashlib.file_digest(f,'sha256').hexdigest()
     if name=='bundle-manifest.json':
      if h!=release['bundle_manifest_sha256']:raise PermissionError('archive_manifest_changed')
      continue
     entry.update(type='file',bytes=row.size,sha256=h)
    elif row.isdir():entry['type']='directory'
    elif row.issym():entry.update(type='symlink',target=row.linkname)
    elif row.islnk():
     key=unicodedata.normalize('NFC',row.linkname[len(prefix):])
     if not row.linkname.startswith(prefix) or actual.get(key,{}).get('type')!='file':raise PermissionError('unsafe_archive_hardlink')
     entry={**actual[key],**entry}
    else:raise PermissionError('unexpected_archive_object')
    if expected.get(name)!=entry:raise PermissionError('archive_member_not_materialized_program:'+name)
    actual[name]=entry
  if actual!=expected:raise PermissionError('archive_is_incomplete')
  m.write(verified,{'archive_sha256':release['archive']['sha256'],'bundle_manifest_sha256':release['bundle_manifest_sha256'],'objects':len(actual),'all_archive_contents_streamed':True,'materialized_inventory_equal':True,'not_an_independent_rebuild_claim':True})
 elif m.read(verified)['archive_sha256']!=release['archive']['sha256']:raise PermissionError('stale_archive_readback')
 if a.target.exists():raise FileExistsError('new_native_environment_target_required')
 # Targets are owner-authorized qualification children of the release area.
 resources=m.resources()
 allowed=Path(resources.get('environment_roots',{}).get(a.environment,resources['release_root'])).resolve()
 if not a.target.resolve().is_relative_to(allowed):raise PermissionError('qualification_target_not_authorized_release_area')
 a.target.mkdir(parents=True);home=a.target/'operator-home';home.mkdir(mode=0o700);install=a.target/'Hermes-BNN-Full'
 subprocess.run(['/bin/cp','-cRp',str(bundle),str(install)],check=True)
 objects=m.verify_tree(install,release['bundle_manifest_sha256'])
 # FinderInfo/ResourceFork are generated cloud metadata, not signed vendor bytes.
 # Remove only these two attributes from the NEW clone; quarantine is preserved.
 app=install/'Hermes/Zotero/app/Zotero.app';metadata=[]
 for attribute in ['com.apple.FinderInfo','com.apple.ResourceFork']:
  p=subprocess.run(['/usr/bin/xattr','-dr',attribute,str(app)],capture_output=True,text=True)
  metadata.append({'attribute':attribute,'exit_code':p.returncode,'scope':'new qualification clone only'})
 check=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],capture_output=True,text=True)
 if check.returncode:raise PermissionError('vendor_signature_before_bootstrap:'+check.stderr[:1000])
 env=m.clean_environment(home);env.update(BNN_ENVIRONMENT=a.environment,BNN_PORT_BASE=str(m.read(m.ROOT/'environments'/f'{a.environment}.json')['port_base']))
 m.logged(['/bin/bash',install/'install.sh'],env,install,a.target/'native-install.log')
 native=m.read(install/'Hermes/state/full-platform-verification.json');cfg=m.read(install/'Hermes/Memory/settings.json')
 assert len(native['five_required_controls'])==5 and native['Intake_registered']
 assert cfg['profile_home']==str(install/'Hermes/data')
 assert cfg['agentmemory_url']=='http://127.0.0.1:'+env['BNN_PORT_BASE']
 assert cfg['neo4j_uri']=='bolt://127.0.0.1:'+str(int(env['BNN_PORT_BASE'])+1)
 profile_config=m.read(install/'Hermes/data/config.yaml')
 assert profile_config['research']=={'integration_mode':'foundation','workspace_root':str(install/'Hermes/workspace/research-runs')}
 skills=next(x for x in cfg['tool_policy']['rules'] if x['id']=='native.skills.metadata')
 assert skills['tool']=='skills_list' and skills['effect']=='read_local' and skills['roles']==['parent']
 bundled=next(x for x in cfg['tool_policy']['rules'] if x['id']=='native.skills.bundled')
 assert bundled['roles']==['parent'] and 'hermes-agent' in bundled['arguments_schema']['properties']['name']['enum']
 assert profile_config['skills']['inline_shell'] is False
 assert not any((install/'Hermes'/n).exists() for n in ['data/auth.json','private/voyage.key','private/telegram.token'])
 subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True)
 receipt={'contract':'BNNNativeEnvironmentQualificationV1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':a.environment,'build_id':release['build_id'],'source_commit':release['source_commit'],'archive_sha256':release['archive']['sha256'],'materialized_objects_verified':objects,'archive_readback':str(verified),'native_install_complete':True,'five_required_controls':native['five_required_controls'],'Intake_registered':True,'instance_id':m.read(install/'Hermes/state/bootstrap.json')['instance_id'],'profile_home':cfg['profile_home'],'state_root':cfg['state_root'],'agentmemory_url':cfg['agentmemory_url'],'neo4j_uri':cfg['neo4j_uri'],'supplier_signature_valid':True,'metadata_treatment':metadata,'owner_credentials_copied':False,'production_changed':False,'live_model_or_Telegram_claimed':False,'production_promotable':False,'installer_used_verified_full_program_tree':True,'archive_transport':'Every member streamed and compared; native installation uses APFS clone to avoid a second 13GB write','operator_adapter_sha256':m.digest(Path(__file__)),'operator_source_commit':m.git('rev-parse','HEAD')}
 m.write(a.target/'qualification.json',receipt)
 operator_state=m.ROOT.parent/'.operator/environments.json'
 registry=m.read(operator_state) if operator_state.exists() else {}
 entry={'installation':str(install),'home':str(home),'qualification':str(a.target/'qualification.json'),'build_id':release['build_id'],'instance_id':receipt['instance_id'],'native_initialized':True,'external_accounts_connected':False}
 registry=register_qualification(registry,a.environment,entry)
 m.write(operator_state,registry)
 print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
