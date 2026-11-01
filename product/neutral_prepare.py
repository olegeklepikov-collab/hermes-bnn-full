"""Portable fresh-profile bootstrap. No account/history migration and no provider call."""
import argparse,hashlib,json,os,secrets,sqlite3,subprocess,sys,uuid
from pathlib import Path
ROOT_TOKEN='__HERMES_ROOT__'

def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600)
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def convert(x,root,identity):
 def s(t):return t.replace(ROOT_TOKEN,str(root)).replace('__USER_HOME__',str(Path.home())).replace('__INSTANCE_ID__',identity)
 if isinstance(x,str):return s(x)
 if isinstance(x,list):return [convert(v,root,identity) for v in x]
 if isinstance(x,dict):return {s(k):convert(v,root,identity) for k,v in x.items()}
 return x

def environment(root):
 e={k:v for k,v in os.environ.items() if k in {'HOME','PATH','TMPDIR','LANG','LC_ALL'}}
 e.update(HERMES_HOME=str(root/'data'),HERMES_BNN_ROOT=str(root),HERMES_BN_ROOT=str(root),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(root/'hermes-agent'),DOLT_ROOT_PATH=str(root/'Dolt/local-state'),BD_NON_INTERACTIVE='1',BEADS_NO_GIT_OPS='1',BEADS_DIR=str(root/'Beads/workspace/.beads'),BEADS_ACTOR='Hermes local owner',DO_NOT_TRACK='1',BD_DISABLE_METRICS='1',BD_DISABLE_EVENT_FLUSH='1')
 return e

def run(argv,root,label,**extra):
 p=subprocess.run(list(map(str,argv)),env=environment(root),cwd=extra.pop('cwd',root),capture_output=True,text=True,timeout=120,**extra)
 if p.returncode:raise RuntimeError(label+': '+p.stderr[-1800:]+p.stdout[-800:])
 return p.stdout

def verify_suppliers(bundle):
 root=bundle/'Hermes';env=environment(root);env['DYLD_LIBRARY_PATH']=os.pathsep.join(str(p) for p in (bundle/'NativeEnvironment/opt/homebrew/Cellar').glob('*/*/lib'));rows=[]
 for folder,name,source in [('foundation-release','hermes-foundation-bridge-0.14.0b1.zip','foundation-source'),('research-release','hermes-research-report-0.44.0b2.zip','research-source')]:
  base=root/'UDR/software'/folder
  r=subprocess.run([str(bundle/'NativeEnvironment/opt/homebrew/bin/minisign'),'-Vm',str(base/name),'-p',str(base/'release-signing.pub')],env=env,capture_output=True,text=True,timeout=20)
  if r.returncode:raise PermissionError('supplier_signature_verification_failed:'+folder)
  manifest=json.loads((base/source/'bundle-manifest.json').read_text())
  for item in manifest['files']:
   p=base/source/item['path']
   if p.is_symlink() or not p.resolve().is_relative_to((base/source).resolve()) or sha(p)!=item['sha256']:raise PermissionError('supplier_source_verification_failed:'+folder)
  rows.append({'component':folder,'archive_sha256':sha(base/name),'signature_valid':True,'source_files_verified':len(manifest['files'])})
 return rows


def initial_settings(bundle,identity):
 root=bundle/'Hermes'
 cfg=convert(json.loads((bundle/'configuration/memory.template.json').read_text()),root,identity)
 base=int(os.environ.get('BNN_PORT_BASE','65000'))
 if not 1024<=base<=65499:raise ValueError('service_port_base_out_of_range')
 cfg['service_port_base']=base
 cfg['agentmemory_url']='http://127.0.0.1:'+str(base)
 cfg['neo4j_uri']='bolt://127.0.0.1:'+str(base+1)
 return cfg

def initialize(bundle):
 root=bundle/'Hermes';marker=root/'state/bootstrap.json'
 suppliers=verify_suppliers(bundle)
 previous=json.loads(marker.read_text()) if marker.exists() else None
 if previous and previous['status']!='initializing':raise FileExistsError('Fresh initialization complete; do not overwrite owner state')
 cfg=initial_settings(bundle,previous['instance_id'] if previous else str(uuid.uuid4()))
 identity=cfg['namespace']['owner_id'];pkg=Path(cfg['package_root'])
 origin=Path(json.loads((pkg/'compute-runtime.json').read_text())['runtime_root']).parents[2]
 cfg['path_relocations']=[{'from':str(origin),'to':str(root),'owner_id':identity}]
 for directory in ['workspace','workspace/deliverables','Beads/workspace','Beads/config','Beads/local-state','Dolt/databases','Dolt/local-state','state/authority','private','Identity/authority','data/skills','data/memories','Cognee-W2/state','Cognee-W2/software']:
  (root/directory).mkdir(parents=True,exist_ok=True,mode=0o700)
 save(marker,{'status':'initializing','instance_id':identity,'no_source_owner_authority':True})
 for name in ['memory-host.key']:
  p=root/'state/authority'/name
  if not p.exists():p.write_bytes(secrets.token_bytes(32));p.chmod(0o600)
 cfg['host_key']=str(root/'state/authority/memory-host.key')
 cfg['native_session_databases']=[str(root/'data/state.db')]
 # Service endpoints were selected by initial_settings before any owner state was created.
 cfg['neo4j_password_file']=str(root/'private/neo4j.password');cfg['agentmemory_key_file']=str(root/'private/agentmemory.token')
 cfg['voyage_key_file']=str(root/'private/voyage.key');cfg['code_path']=os.pathsep.join([str(root/'R/serena-bin'),str(root/'UDR/software/bin'),'/usr/bin','/bin'])
 cfg['zotero_root']=str(root/'state/services/zotero')
 for name in ['neo4j.password','agentmemory.token','embedding-local.token']:
  p=root/'private'/name
  if not p.exists():p.write_text(secrets.token_urlsafe(32));p.chmod(0o600)
 # Empty independent procedural/deep identity; no source SOUL or approvals.
 if not (root/'data/SOUL.md').exists():(root/'data/SOUL.md').write_text('# Hermes\n\nИсследовательский помощник. Отделяй факты, гипотезы и ограничения. Личность владельца не задана.\n')
 sys.path[:0]=[str(root/'Identity/releases/0.2.1'),str(pkg),str(root/'hermes-agent')]
 from bnn_identity.store import initialize as identity_init,Store as IdentityStore
 vault=Path(cfg['identity_runtime']['vault_root'])
 identity_result=IdentityStore(vault).status() if vault.exists() else identity_init(vault,instance_id=identity,agent_id='Hermes',profiles={'main':str(root/'data/SOUL.md')})
 cfg['identity_runtime']['policy_sha256']=sha(Path(cfg['identity_runtime']['vault_root'])/'policy.json')
 cfg['identity_runtime']['package_manifest_sha256']=sha(Path(cfg['identity_runtime']['package_root'])/'manifest.json')
 # Local GSD authority is new. Signed Engine and Research/Foundation bytes stay fixed.
 gs=convert(json.loads((bundle/'configuration/gsd.template.json').read_text()),root,identity)
 gs.update(state_dir=str(root/'state/modules/gsd/state'),operator_dir=str(root/'state/modules/gsd/operator'))
 operator=Path(gs['operator_dir']);(operator/'receipts').mkdir(parents=True,exist_ok=True,mode=0o700);Path(gs['state_dir']).mkdir(parents=True,exist_ok=True,mode=0o700)
 gs['anchor_file']=str(operator/'anchor.json')
 for name in ['store','native','grant']:
  p=operator/(name+'.key')
  if not p.exists():p.write_bytes(secrets.token_bytes(32));p.chmod(0o600)
  gs[name+'_key']=str(p)
 gs_path=operator/'settings.json';save(gs_path,gs)
 gm=cfg['modules']['gsd'];gm['settings_file']=str(gs_path)
 gm['files']={p:sha(p) for p in gm['files'] if '/state/' not in p};gm['files'][str(gs_path)]=sha(gs_path)
 sys.path.insert(0,gm['host_package'])
 from bn_gsd.bridge import Bridge
 bridge=Bridge(gs_path)
 if not Path(gs['anchor_file']).exists():bridge.call('init')
 gsd=bridge.call('component_inventory')
 assert gsd['engine_release']=='3.0.3' and gsd['source_tree_verified']
 rm=cfg['modules']['research'];rm['state_root']=str(root/'state/modules/research/foundation')
 for key,value in [('user.name','Hermes local owner'),('user.email','local@localhost'),('versioncheck.disabled','true')]:run([root/'Dolt/bin/dolt','config','--global','--add',key,value],root,'dolt-config')
 sys.path[:0]=rm['source_paths']
 from hermes_foundation_bridge.runtime import RuntimeCoordinator
 from hermes_foundation_bridge.dolt_state import DoltStateAdapter
 from hermes_foundation_bridge.artifacts import ArtifactService
 fr=Path(rm['state_root']);foundation=[RuntimeCoordinator(fr).migration_receipt(apply=True),DoltStateAdapter(fr,executable=rm['dolt_executable']).migrate(apply=True),ArtifactService(fr).prepare(dry_run=False)]
 rm['files']={p:sha(p) for p in rm['files']}
 # Primary Beads database belongs only to this new installation.
 run([root/'Dolt/bin/dolt','config','--global','--add','user.name','Hermes local owner'],root,'dolt-config')
 run([root/'Dolt/bin/dolt','config','--global','--add','user.email','local@localhost'],root,'dolt-config')
 if not (root/'Beads/workspace/.beads/config.yaml').exists():run([root/'Beads/bin/bd','init','--prefix','hnew','--stealth','--non-interactive','--skip-agents','--skip-hooks'],root,'beads-init',cwd=root/'Beads/workspace')
 bead_receipt=root/'state/bootstrap-bead.json'
 if bead_receipt.exists():bead=json.loads(bead_receipt.read_text())
 else:
  existing=json.loads(run([root/'bin/bd-bnn','list','--json','--all'],root,'beads-recovery'))
  matches=[r for r in existing if r['title']=='Fresh installation readiness']
  if len(matches)>1:raise RuntimeError('ambiguous_bootstrap_bead')
  bead=matches[0] if matches else json.loads(run([root/'bin/bd-bnn','create','Fresh installation readiness','--type','task','--json'],root,'beads-bootstrap'))
  save(bead_receipt,bead)
 cfg['task_pin_probe']=bead['id'];cfg['working_beads']['files']={p:sha(p) for p in cfg['working_beads']['files']}
 from bn_memory.store import Store
 from bn_memory.store import canonical,sha as text_sha
 from bn_memory.embedding_contract import space
 from bn_memory.backend_policy import resource_hash
 target_ids={k:uuid.uuid4().hex for k in ['agentmemory','graphiti','zvec']}
 save(root/'state/projection-target-identities.json',target_ids)
 cfg['projection_targets']={backend:text_sha(canonical({'contract':'BNProjectionTargetV1','backend':backend,'instance':value,'namespace':cfg['namespace'],'embedding_space':space(cfg)['space_id'] if backend in {'agentmemory','zvec'} else None})) for backend,value in target_ids.items()}
 if cfg.get('public_crossref'):cfg['public_crossref']['client_sha256']=sha(cfg['public_crossref']['client_file'])
 for backend,entry in cfg['backend_policy']['allow'].items():entry['resource_sha256']=resource_hash(cfg,backend)
 if not (Path(cfg['state_root'])/'memory.sqlite').exists():Store(cfg['state_root'],cfg).initialize()
 save(root/'Memory/settings.json',cfg)
 cognee=root/'Cognee-W2'
 if not (cognee/'software/venv').is_symlink():(cognee/'software/venv').symlink_to(Path('../../Cognee/software/venv'))
 save(cognee/'state/instance.json',{'instance_id':'hermes-'+identity})
 profile={'model':{'provider':'openai-codex','default':'gpt-6.1-sol'},'agent':{'reasoning_effort':'xhigh','max_turns':0,'run_budget_seconds':None},'compression':{'enabled':True,'in_place':True,'checkpoint_required':True},
  'research':{'integration_mode':'foundation','workspace_root':str(root/'workspace/research-runs')},
  'skills':{'inline_shell':False},
  'plugins':{'enabled':['bn-common-memory'],'entries':{'bn-common-memory':{'enabled':True,'settings':{'config_file':str(root/'Memory/settings.json')}}}},
  'mcp_servers':{'context':{'command':str(root/'hermes-agent/venv/bin/python'),'args':[str(pkg/'bn_memory/server.py'),str(root/'Memory/settings.json')],'env':{'HERMES_HOME':str(root/'data'),'PYTHONPATH':os.pathsep.join([str(pkg),str(root/'hermes-agent')]),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}}},
  'memory':{'provider':'bnn-memory-checkpoint','checkpoint_settings_file':str(root/'Memory/settings.json')},'platform_toolsets':{'cli':['context','bnn_modules','skills']},'gateway':{'standalone':True,'multiplex_profiles':False}}
 save(root/'data/config.yaml',profile)
 save(root/'data/execution-controls.json',{'version':1,'required':{x:['bn-common-memory'] for x in ['tool','tool_result','llm','auxiliary','subagent_launch']},'timeout_seconds':5})
 (root/'bin/hermes').write_text('''#!/bin/bash
set -eu
hermes_install_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$hermes_install_root/environment.sh"
exec "$hermes_install_root/hermes-agent/venv/bin/python" -m hermes_cli.main "$@"
''');(root/'bin/hermes').chmod(0o700)
 marker_body={'status':'fresh_local_initialized','instance_id':identity,'empty_previous_memories':True,'identity':identity_result,'GSD':gsd,'Foundation':foundation,'suppliers':suppliers,'bootstrap_bead':cfg['task_pin_probe'],'external_credentials_copied':False,'provider_execution_verified':False,'service_execution_verified':False}
 save(marker,marker_body)
 return {'fresh_local_initialized':True,'GSD_engine':gsd['engine_release'],'Foundation_initialized':True,'Beads_initialized':True,'provider_execution_verified':False}

def verify(bundle):
 root=bundle/'Hermes';cfg=json.loads((root/'Memory/settings.json').read_text());pkg=Path(cfg['package_root'])
 sys.path[:0]=[str(pkg),str(root/'hermes-agent')]
 from bn_memory.store import Store
 from bn_memory.broker import Broker
 store=Store(cfg['state_root'],cfg)
 with sqlite3.connect(Path(cfg['state_root'])/'memory.sqlite') as db:
  tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
  integrity=db.execute('PRAGMA quick_check').fetchone()[0]
  counts={t:db.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables if t in {'records','sources','tasks','module_sessions','result_artifacts','result_deliveries','work_events'}}
 assert integrity=='ok' and all(v==0 for v in counts.values()),counts
 b=Broker(cfg);sid='fresh-local-acceptance';b.store.bind(sid)
 from bn_memory.plugin import Host
 host=Host(root/'Memory/settings.json');host.close()
 run([root/'Dolt/bin/dolt','config','--global','--add','versioncheck.disabled','true'],root,'dolt-local-version-check')
 result={'integrity':integrity,'empty_primary_tables':counts,'required_host_initialized':True,'CLI_version':run([root/'bin/hermes','--version'],root,'native-version').strip(),
  'Beads_version':run([root/'bin/bd-bnn','version'],root,'native-beads').strip(),'Dolt_version':run([root/'Dolt/bin/dolt','version'],root,'native-dolt').strip(),
  'document_imports':run([root/'DocumentRuntime/venv/bin/python','-c','import pymupdf,openpyxl,xlrd; print("PDF XLSX XLS imports OK")'],root,'document-imports').strip(),
  'no_provider_credentials':not any((root/p).exists() for p in ['data/auth.json','private/voyage.key','private/telegram.token']),
  'service_execution_verified':False,'provider_execution_verified':False,'fresh_data_initialization_only':True}
 assert result['no_provider_credentials']
 save(root/'state/fresh-verification.json',result);return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['initialize','verify']);p.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parent);a=p.parse_args()
 print(json.dumps(globals()[a.action](a.bundle.resolve()),ensure_ascii=False,indent=2))
