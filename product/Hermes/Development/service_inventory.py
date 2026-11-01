"""Isolated legacy migration and read-only MCP discovery. Never renews BN tokens."""
from pathlib import Path
import asyncio,hashlib,json,os,re,shutil,time
from urllib.parse import urlsplit
import yaml
from service_docs import ROOT,BASE,DIRECTORIES,dump

BN=ROOT.parent/'Hermes BN'; SERVICE=ROOT/'Services'; AUTH=ROOT/'state/authority/services'
SERVER_DIR={**DIRECTORIES,'keenable-select':'Keenable','nimble-docs':'Nimble','parallel-search':'Parallel','parallel-task':'Parallel','openalex-api':'OpenAlex','beads-dolt':'Dolt'}
SKIP={'context','udr'}
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def private_dump(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700);dump(path,value)
def rewrite(value,source,target):
 if isinstance(value,str):return value.replace(str(source),str(target))
 if isinstance(value,list):return [rewrite(v,source,target) for v in value]
 if isinstance(value,dict):return {k:rewrite(v,source,target) for k,v in value.items()}
 return value
def env_values():
 from dotenv import dotenv_values
 return {k:v for k,v in dotenv_values(BN/'data/.env').items() if v}
def resolve(value,env):
 if not isinstance(value,str):return value
 return re.sub(r'\$\{([A-Z0-9_]+)\}',lambda m:env.get(m[1],''),value)
def inventory():
 BASE.mkdir(parents=True,exist_ok=True);AUTH.mkdir(parents=True,exist_ok=True,mode=0o700);AUTH.chmod(0o700)
 cfg=yaml.safe_load((BN/'data/config.yaml').read_text());env=env_values();public=[];software={}
 memory=json.loads((ROOT/'Memory/settings.json').read_text())
 for name,old in cfg['mcp_servers'].items():
  if name in SKIP:continue
  folder=SERVER_DIR[name];source=ROOT/folder;target=SERVICE/'software'/folder
  if folder not in software:
   manifest={}
   for p in source.glob('*.py'):
    text=p.read_text();text=text.replace(str(BN),str(ROOT))
    # The client lives in its own fresh writable service state, never legacy BN data.
    text=text.replace("Path('"+str(ROOT/folder)+"')","Path(__file__).resolve().parent")
    text=text.replace('Path("'+str(ROOT/folder)+'")','Path(__file__).resolve().parent')
    q=target/p.name;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(text);q.chmod(0o600)
    manifest[p.name]={'source_sha256':digest(p),'installed_sha256':digest(q)}
   for sub in ['config','источники','fixtures']:
    if (source/sub).exists():
     for p in (source/sub).rglob('*'):
      if not p.is_file() or p.suffix not in {'.json','.yaml','.yml','.txt','.md','.xml','.xsd'}:continue
      if any(x in p.name.lower() for x in ['before','backup','token','key-entry','request.lock','last-request','transport-state','lab.pid']):continue
      q=target/p.relative_to(source);q.parent.mkdir(parents=True,exist_ok=True)
      data=p.read_text(errors='strict').replace(str(BN),str(ROOT)).replace(str(ROOT/folder),str(target));q.write_text(data);q.chmod(0o600)
   for sub in ['config','checks','exports','cache','projects','documents','logs','stream-results','imports']:(target/sub).mkdir(parents=True,exist_ok=True)
   software[folder]=manifest
  item={'service':name,'directory':folder,'legacy_enabled':old.get('enabled',True),'legacy_tool_filter':old.get('tools',{}),'source_config_sha256':digest(BN/'data/config.yaml'),'transport':'http' if old.get('url') else 'stdio','state_root':str(target),'authentication':'api_key_or_public','credential_present':False,'discovery':'not_run'}
  item['tool_timeout']=max(180,int(old.get('tool_timeout',old.get('timeout',180))))
  secret={'headers':{},'env':{}}
  if old.get('url'):
   u=old['url'];parsed=urlsplit(u)
   if parsed.scheme!='https' or parsed.username:raise ValueError('service_https_required')
   item['url']=u
   for k,v in old.get('headers',{}).items():secret['headers'][k]=resolve(v,env)
   if old.get('auth')=='oauth':
    p=BN/'data/mcp-tokens'/(name+'.json');item['authentication']='oauth_access_only_no_shared_refresh'
    if p.exists():
     t=json.loads(p.read_text());expires=t.get('expires_at',p.stat().st_mtime+int(t.get('expires_in',0)))
     item['access_expires_at']=expires
     if t.get('access_token') and (not expires or expires>time.time()+30):secret['headers']['Authorization']='Bearer '+t['access_token']
    item['reauthorization_required']=not bool(secret['headers'].get('Authorization'))
    own=ROOT/'data/mcp-tokens'/(name+'.json')
    if own.exists():
     item['authentication']='independent_BNN_oauth';item['oauth']=dict(old.get('oauth',{}));item['oauth']['client_name']='Hermes BNN — service integration';item.pop('access_expires_at',None);item['reauthorization_required']=False;secret['headers'].pop('Authorization',None)
     if name=='undermind':item['oauth'].pop('client_name',None)
   item['credential_present']=any(k.lower() in {'authorization','x-api-key'} and bool(v) for k,v in secret['headers'].items())
  else:
   item['command']=str(ROOT/'hermes-agent/venv/bin/python');item['args']=[str(target/'mcp_server.py')]
   if name=='asreview':item['command']=str(ROOT/'ASReview/runtime/bin/python')
   if name in {'beads','dolt','beads-dolt'}:
    item['command']=str(ROOT/'Dolt/runtime/bin/python');item['args']=[str(target/('workspace_mcp.py' if name=='beads-dolt' else 'scoped_mcp.py'))]+([] if name=='beads-dolt' else [name])
   if name=='rstats':
    item['args']=rewrite(old.get('args',[]),BN,ROOT);item['discovery_constraint']='Existing isolated evaluator must be found and pinned; no unsandboxed R execution.'
   item['env']={'HERMES_HOME':str(ROOT/'data'),'HERMES_BN_ROOT':str(ROOT),'HERMES_BNN_ROOT':str(ROOT),'PYTHONPATH':str(ROOT/'hermes-agent'),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}
   needed={'tavily':['TAVILY_API_KEY'],'semanticscholar':['SEMANTIC_SCHOLAR_API_KEY'],'pubmed':['NCBI_API_KEY'],'openalex-api':['OPENALEX_API_KEY'],'russianresearch':['TAVILY_API_KEY']}.get(name,[])
   for key in needed:
    if env.get(key):secret['env'][key]=env[key]
   item['credential_present']=bool(secret['env']);item['authentication']='local_or_api_key'
  private_dump(AUTH/(name+'.json'),secret);item['authority_file']=str(AUTH/(name+'.json'))
  # Maintain original access holds. They are not connection failures to bypass.
  if name in {'webofscience','russianresearch'}:item['access_hold_retained']=True
  if name=='zotero':
   existing=json.loads((Path(memory['zotero_root'])/'identity.json').read_text());oldidentity=json.loads((target/'config/identity.json').read_text())
   oldidentity.update(base_url=existing['base_url'],server_id=existing['server_id'],data=str(Path(memory['zotero_root'])/'data'),output_root=str(target/'exports'),import_roots=list(memory['projects'].values()))
   private_dump(target/'config/identity.json',oldidentity)
   private_dump(target/'config/authorization.json',json.loads((Path(memory['zotero_root'])/'authorization.json').read_text()))
  if name=='tavily':
   # Replace import-time dotenv/SecretScope lookup with this service's local vault.
   p=target/'api.py';text=p.read_text();text=text.replace("load_hermes_dotenv();key=get_secret('TAVILY_API_KEY')","key=json.loads((Path(os.environ['HERMES_BNN_SERVICES_AUTH'])/'tavily.json').read_text())['env'].get('TAVILY_API_KEY')")
   if 'import os' not in text:text='import os\n'+text
   p.write_text(text);software[folder]['api.py']['installed_sha256']=digest(p)
  if name=='pubmed':
   shutil.copytree(source/'vendor',target/'vendor',dirs_exist_ok=True)
  if name=='openalex-api':
   credential=BN/'OpenAlex/credentials.json'
   if credential.exists():
    value=json.loads(credential.read_text());private_dump(target/'credentials.json',value)
    secret['env']['OPENALEX_API_KEY']=value['api_key'];private_dump(AUTH/(name+'.json'),secret);item['credential_present']=True
  if name=='asreview':
   item['env'].update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
   p=target/'config/model-snapshots.json'
   if (source/'config/model-snapshots.json').exists():p.write_text((source/'config/model-snapshots.json').read_text().replace(str(BN),str(ROOT)))
  if name in {'russianresearch','zotero','openalex-api'} and (source/'deps').exists():
   item['env']['PYTHONPATH']=str(source/'deps')+os.pathsep+item['env']['PYTHONPATH']
  if name=='rstats':
   item['command']=str(ROOT/'hermes-agent/venv/bin/python')
   code=(ROOT/'R/scripts/server.R').read_text();(target/'server.R').write_text(code)
   shutil.copyfile(ROOT/'Development/service_r_launch.py',target/'r_launch.py')
   shutil.copyfile(ROOT/'Development/service_r_bootstrap.R',target/'bootstrap.R')
   item['args']=['-I','-S','-B',str(target/'r_launch.py'),'--vanilla','--slave','-f',str(target/'bootstrap.R')]
   item['env'].update(HERMES_BN_R_HOME=str(target),R_HOME='/Library/Frameworks/R.framework/Resources',R_SHARE_DIR='/Library/Frameworks/R.framework/Resources/share',R_INCLUDE_DIR='/Library/Frameworks/R.framework/Resources/include',R_DOC_DIR='/Library/Frameworks/R.framework/Resources/doc',R_LIBS_USER=str(ROOT/'R/packages')+':'+str(ROOT/'R/serena-library'),R_PROFILE_USER='/dev/null',R_ENVIRON_USER='/dev/null',R_MAKEVARS_USER='/dev/null',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
   item['untrusted_evaluator']=True
   item['env'].update(R_DEFAULT_PACKAGES='base,methods',R_LIBS_USER=str(target/'framework-library'),HERMES_R_CODE_ROOT=str(target))
  public.append(item)
 private_dump(SERVICE/'registry.private.json',{'version':1,'services':public,'software':software,'source':'BN inventory copied read-only; credentials never enter public documentation','bn_modified':False})
 status={'task':'bnn-x4y.28','services':len(public),'original_servers':len(cfg['mcp_servers']),'credentials_printed':False,'source_modified':False,'registry':str(SERVICE/'registry.private.json'),'oauth_access_only':True}
 dump(BASE/'inventory-status.json',status)
 dump(BASE/'inventory.public.json',{'services':[{k:v for k,v in x.items() if k not in {'authority_file','url','env','command','args','state_root'}} for x in public],'software':software})
 return status

async def mcp_session(entry,command='list',name=None,args=None):
 from contextlib import AsyncExitStack
 from mcp import ClientSession,StdioServerParameters
 from mcp.client.stdio import stdio_client
 from mcp.client.streamable_http import streamable_http_client
 import httpx2
 secret=json.loads(Path(entry['authority_file']).read_text())
 async with AsyncExitStack() as stack:
  if entry['transport']=='http':
   if entry.get('reauthorization_required'):return {'ok':False,'code':'independent_oauth_required','tools':[]}
   auth=None
   if entry.get('authentication')=='independent_BNN_oauth':
    from tools.mcp_oauth_manager import get_manager
    auth=get_manager().get_or_build_provider(entry['service'],entry['url'],entry.get('oauth'))
   http=await stack.enter_async_context(httpx2.AsyncClient(headers=secret['headers'],auth=auth,timeout=45,trust_env=False,follow_redirects=False))
   streams=await stack.enter_async_context(streamable_http_client(entry['url'],http_client=http))
  else:
   script=next((x for x in entry['args'] if x.startswith('/')),None)
   if not Path(entry['command']).exists() or script and not Path(script).exists():return {'ok':False,'code':'isolated_executor_missing','tools':[]}
   env={k:v for k,v in os.environ.items() if k in {'HOME','TMPDIR','PATH','LANG','LC_ALL','SSL_CERT_FILE'}}
   env.update(entry['env']);env['HERMES_BNN_SERVICES_AUTH']=str(AUTH)
   tmp=Path(entry['state_root'])/'.tmp';tmp.mkdir(exist_ok=True);env['TMPDIR']=str(tmp);env['XDG_CACHE_HOME']=str(tmp)
   stderr=(BASE/'discovery-stderr.log').open('a')
   stack.callback(stderr.close)
   from service_sandbox import profile
   sandbox=profile(ROOT,entry)
   streams=await stack.enter_async_context(stdio_client(StdioServerParameters(command='/usr/bin/sandbox-exec',args=['-p',sandbox,entry['command'],*entry['args']],env=env,cwd=entry['state_root']),errlog=stderr))
  session=await stack.enter_async_context(ClientSession(streams[0],streams[1]))
  init=await session.initialize()
  if command=='list':
   result=await session.list_tools();tools=[];cursor=result.next_cursor
   tools.extend(t.model_dump(mode='json',by_alias=True) for t in result.tools)
   while cursor:
    result=await session.list_tools(cursor=cursor);tools.extend(t.model_dump(mode='json',by_alias=True) for t in result.tools);cursor=result.next_cursor
   return {'ok':True,'tools':tools,'instructions':getattr(init,'instructions',None),'serverInfo':init.server_info.model_dump(mode='json',by_alias=True),'capabilities':init.capabilities.model_dump(mode='json',by_alias=True)}
  result=await session.call_tool(name,arguments=args or {})
  return result.model_dump(mode='json',by_alias=True)
async def discovery_all():
 registry=json.loads((SERVICE/'registry.private.json').read_text());sem=asyncio.Semaphore(4)
 async def run(entry):
  async with sem:
   if entry['service'] in {'beads','dolt','beads-dolt'}:
    return {'service':entry['service'],'discovered':False,'tools':0,'status':'existing_BNN_primary_interfaces_retained_no_legacy_port_rebind'}
   previous=BASE/'catalogues'/(entry['service']+'.json')
   if previous.exists() and json.loads(previous.read_text()).get('ok'):
    value=json.loads(previous.read_text())
    return {'service':entry['service'],'discovered':True,'tools':len(value['tools']),'retained_same_inventory':True}
   try:value=await asyncio.wait_for(mcp_session(entry),timeout=65)
   except Exception as e:
    while isinstance(e,BaseExceptionGroup) and e.exceptions:e=e.exceptions[0]
    value={'ok':False,'code':type(e).__name__,'tools':[]}
    response=getattr(e,'response',None)
    if response is not None:value['http_status']=response.status_code
    message=str(e)
    if not any(x in message.lower() for x in ['bearer','token=','api_key=']):value['diagnostic']=message[:350]
   dump(BASE/'catalogues'/(entry['service']+'.json'),value)
   print(json.dumps({'service':entry['service'],'discovered':value['ok'],'tools':len(value['tools']),'code':value.get('code')},ensure_ascii=False),flush=True)
   return {'service':entry['service'],'discovered':value['ok'],'tools':len(value['tools']),'code':value.get('code')}
 results=await asyncio.gather(*(run(e) for e in registry['services']))
 active=[x for x in results if x['service'] not in {'beads','dolt','beads-dolt'}]
 status={'services':results,'all_research_service_catalogues_discovered':all(x['discovered'] for x in active),'new_business_tool_calls':0,'oauth_refreshes':'independent BNN OAuth manager may refresh only its own grants'}
 dump(BASE/'discovery-status.json',status);return status
def discover():return asyncio.run(discovery_all())
def r_probe():
 import subprocess
 entry=next(e for e in json.loads((SERVICE/'registry.private.json').read_text())['services'] if e['service']=='rstats')
 from service_sandbox import profile
 sandbox=profile(ROOT,entry)
 env=entry['env'].copy();env.update(TMPDIR=str(Path(entry['state_root'])/'.tmp'),HOME=entry['state_root'],PATH='/usr/bin:/bin',HERMES_R_PROBE='1')
 run=subprocess.run(['/usr/bin/sandbox-exec','-p',sandbox,entry['command'],*entry['args']],env=env,capture_output=True,text=True,timeout=30)
 result={'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'sandbox_sha256':hashlib.sha256(sandbox.encode()).hexdigest()};dump(BASE/'r-startup-probe.json',result);return result

def authorize(service):
 entry=next(e for e in json.loads((SERVICE/'registry.private.json').read_text())['services'] if e['service']==service)
 if service not in {'scite','undermind','alphaxiv','pendar','openalex'}:raise ValueError('selected_oauth_service_required')
 source=yaml.safe_load((BN/'data/config.yaml').read_text())['mcp_servers'][service]
 async def login():
  from tools.mcp_oauth_manager import get_manager
  from mcp import ClientSession
  from mcp.client.streamable_http import streamable_http_client
  import httpx2
  oauth={**source.get('oauth',{}),'client_name':'Hermes BNN — '+service,'timeout':900}
  if service=='undermind':oauth.pop('client_name',None)
  auth=get_manager().get_or_build_provider(service,entry['url'],oauth)
  async with httpx2.AsyncClient(auth=auth,timeout=180,trust_env=False) as http:
   async with streamable_http_client(entry['url'],http_client=http) as streams:
    async with ClientSession(streams[0],streams[1]) as s:
     init=await s.initialize();r=await s.list_tools()
     dump(BASE/'catalogues'/(service+'.json'),{'ok':True,'tools':[t.model_dump(mode='json',by_alias=True) for t in r.tools],'instructions':getattr(init,'instructions',None),'serverInfo':init.server_info.model_dump(mode='json',by_alias=True),'capabilities':init.capabilities.model_dump(mode='json',by_alias=True),'independent_BNN_oauth':True})
     value={'service':service,'independent_BNN_oauth':True,'tools':len(r.tools),'bn_tokens_modified':False,'copied_refresh_tokens':False}
     dump(BASE/('oauth-'+service+'-status.json'),value);return value
 return asyncio.run(login())
