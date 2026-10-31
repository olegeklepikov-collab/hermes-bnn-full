"""Deployment-side protected input and OAuth. No dependency on an existing BN."""
from pathlib import Path
import asyncio,getpass,hashlib,json,os,re
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'Development/services-20261028'
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 temp=path.with_suffix(path.suffix+'.new');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.chmod(0o600);os.replace(temp,path)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def registry():return json.loads((ROOT/'Services/registry.private.json').read_text())
def contact():
 email=input('Ваш технический контакт для Crossref и NCBI: ').strip()
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('valid_contact_email_required')
 for folder,name in [('Crossref','settings.json'),('PubMed','contact.json')]:
  p=ROOT/'Services/software'/folder/'config'/name;value=json.loads(p.read_text());value['email']=email
  if folder=='Crossref':value.update(email_authorized=True,mode='polite',user_agent='Hermes-BNN/1.0 (mailto:'+email+')')
  save(p,value)
 return {'contact_saved':True,'services':['crossref','pubmed'],'provider_requests_performed':False}
def authorize(service):
 if service not in {'scite','undermind','alphaxiv','pendar','openalex','tinyfish','wiley','elicit'}:raise ValueError('selected_oauth_service_required')
 entry=next(e for e in registry()['services'] if e['service']==service)
 async def login():
  from tools.mcp_oauth_manager import get_manager
  from mcp import ClientSession
  from mcp.client.streamable_http import streamable_http_client
  import httpx2
  cfg=dict(entry.get('oauth',{}));cfg['timeout']=900
  if service=='undermind':cfg.pop('client_name',None)
  else:cfg['client_name']='Hermes BNN — '+service
  auth=get_manager().get_or_build_provider(service,entry['url'],cfg)
  async with httpx2.AsyncClient(auth=auth,timeout=180,trust_env=False) as http:
   async with streamable_http_client(entry['url'],http_client=http) as streams:
    async with ClientSession(streams[0],streams[1]) as session:
     init=await session.initialize();listing=await session.list_tools()
     tools=[t.model_dump(mode='json',by_alias=True) for t in listing.tools]
     while listing.next_cursor:
      listing=await session.list_tools(cursor=listing.next_cursor);tools.extend(t.model_dump(mode='json',by_alias=True) for t in listing.tools)
     result={'ok':True,'tools':tools,'instructions':getattr(init,'instructions',None),'serverInfo':init.server_info.model_dump(mode='json',by_alias=True),'capabilities':init.capabilities.model_dump(mode='json',by_alias=True),'independent_BNN_oauth':True}
     save(BASE/'catalogues'/(service+'.json'),result)
     status={'service':service,'independent_BNN_oauth':True,'tools':len(tools),'copied_refresh_tokens':False};save(BASE/('oauth-'+service+'-status.json'),status);return status
 result=asyncio.run(login())
 if entry.get('connection_hold'):
  from service_lifecycle import quiescent,stop_for_cutover,restart_previous
  cfg=json.loads((ROOT/'Memory/settings.json').read_text());quiescent(cfg);lifecycle=stop_for_cutover()
  reg=registry();selected=next(e for e in reg['services'] if e['service']==service);selected.pop('connection_hold',None);selected['oauth_authorized']=True
  save(ROOT/'Services/registry.private.json',reg);cfg['service_integration']['registry_sha256']=digest(ROOT/'Services/registry.private.json');save(ROOT/'Memory/settings.json',cfg)
  restart_previous(lifecycle)
 result['catalogue_activation_required']=True
 return result

def discover_one(service):
 entry=next(e for e in registry()['services'] if e['service']==service)
 if service not in {'tinyfish','wiley','elicit','scispace'}:raise ValueError('selected_new_MCP_service_required')
 from service_inventory import mcp_session
 value=asyncio.run(mcp_session(entry))
 if not value.get('ok'):raise RuntimeError('selected_service_catalogue_unavailable')
 save(BASE/'catalogues'/(service+'.json'),value)
 return {'service':service,'tools':len(value['tools']),'catalogue_obtained':True,'business_methods_executed':0,'activation_required':True}

def configure_key(provider):
 key=getpass.getpass('Ключ '+provider+' (защищённый ввод, в чат не отправлять): ').strip()
 return apply_key(provider,key)

def apply_key(provider,key):
 aliases={'firecrawl':['firecrawl'],'exa':['exa'],'tavily':['tavily','russianresearch'],'keenable':['keenable','keenable-select'],'nimble':['nimble'],'parallel':['parallel-search','parallel-task'],'consensus':['consensus'],'openalex':['openalex-api'],'semanticscholar':['semanticscholar'],'pubmed':['pubmed']}
 aliases.update({'tinyfish':['tinyfish','tinyfish-api'],'elicit':['elicit-api'],'synapse':['synapse']})
 if provider not in aliases:raise ValueError('known_key_provider_required')
 if not key or re.search(r'\s',key) or len(key)>16384:raise ValueError('one_unbroken_API_key_required')
 cfg=json.loads((ROOT/'Memory/settings.json').read_text());reg=registry()
 from service_lifecycle import quiescent,stop_for_cutover,restart_previous
 quiescent(cfg)
 lifecycle=stop_for_cutover()
 changed=[]
 for entry in reg['services']:
  if entry['service'] not in aliases[provider]:continue
  p=Path(entry['authority_file']);data=json.loads(p.read_text());name=entry['service']
  if provider=='exa':data['headers']['x-api-key']=key
  elif provider=='tinyfish':data['headers']['X-API-Key']=key
  elif provider in {'elicit','synapse'}:data['headers']['Authorization']='Bearer '+key
  elif provider in {'firecrawl','nimble','parallel','consensus'}:data['headers']['Authorization']='Bearer '+key
  elif provider=='keenable':data['headers']['X-API-Key']=key
  else:
   envname={'tavily':'TAVILY_API_KEY','openalex':'OPENALEX_API_KEY','semanticscholar':'SEMANTIC_SCHOLAR_API_KEY','pubmed':'NCBI_API_KEY'}[provider];data['env'][envname]=key
  save(p,data);entry['credential_present']=True;entry.pop('connection_hold',None)
  if provider=='tinyfish' and name=='tinyfish':entry['authentication']='api_key'
  cfg['service_integration']['authority_hashes'][name]=digest(p);changed.append(name)
  root=Path(entry['state_root'])
  if provider=='openalex':save(root/'credentials.json',{'api_key':key})
  if provider in {'semanticscholar','pubmed'}:
   envname='NCBI_API_KEY' if provider=='pubmed' else 'SEMANTIC_SCHOLAR_API_KEY';dest=root/'credentials.env';dest.write_text(envname+'='+key+'\n');dest.chmod(0o600)
 if provider in cfg.get('research_providers',{}).get('providers',{}):
  entry=cfg['research_providers']['providers'][provider];p=Path(entry['key_file']);p.write_text(key);p.chmod(0o600)
  import sys;sys.path.insert(0,cfg['package_root']);from bn_memory.research_providers import resource_hash
  entry['resource_sha256']=resource_hash(cfg,provider)
 save(ROOT/'Services/registry.private.json',reg);cfg['service_integration']['registry_sha256']=digest(ROOT/'Services/registry.private.json');save(ROOT/'Memory/settings.json',cfg)
 restart_previous(lifecycle)
 return {'saved':True,'provider':provider,'updated_connectors':changed,'credential_printed':False,'authentication_verified':False,'next':'Run the finite connection/service check; saving a key is not an authenticated request.'}
