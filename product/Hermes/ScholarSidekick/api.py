"""Official Scholar Sidekick surfaces, explicitly anonymous and paced."""
from __future__ import annotations
import asyncio,dataclasses,fcntl,json,os,sys,time
from pathlib import Path
import requests,jsonschema
P=Path(__file__).resolve().parent;R=P.parent
BASE='https://scholar-sidekick.com';MCP_URL=BASE+'/api/mcp'
sys.path.insert(0,str(P/'deps'))
from scholar_sidekick import ScholarSidekick

def load(p):return json.loads(p.read_text())
def save(p,o):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:json.dump(o,f,ensure_ascii=False,indent=2,default=str)
 os.chmod(p,0o600)
def pace(group):
 path=P/'data'/('pace-'+group+'.txt');path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with path.open('a+') as f:
  os.chmod(path,0o600);fcntl.flock(f,fcntl.LOCK_EX);f.seek(0);last=float(f.read() or 0)
  interval={'format':6.3,'audit':8.2,'other':1.1}[group]
  time.sleep(max(0,interval-(time.time()-last)));f.seek(0);f.truncate();f.write(str(time.time()));f.flush()
def mcp_group(name):return 'format' if name in {'formatCitation','exportCitation','resolveIdentifier'} else 'audit' if name=='auditBibliography' else 'other'

async def mcp(command,name,args):
 from mcp import ClientSession
 from mcp.client.streamable_http import streamable_http_client
 import httpx2
 sys.path.insert(0,str(R/'hermes-agent'))
 from tools.mcp_tool_config import _load_mcp_config
 config=_load_mcp_config().get('scholarsidekick')
 if not config or config.get('url')!=MCP_URL or config.get('headers') or config.get('auth'):
  raise ValueError('Нужна текущая анонимная настройка Scholar Sidekick в Hermes BN.')
 async with httpx2.AsyncClient(timeout=180) as http:
  async with streamable_http_client(MCP_URL,http_client=http) as streams:
   async with ClientSession(streams[0],streams[1],read_timeout_seconds=180) as s:
    init=await s.initialize();tools=await s.list_tools();catalog={t.name:t for t in tools.tools}
    if command=='catalog':
     prompts=await s.list_prompts() if init.capabilities.prompts else None
     resources=await s.list_resources() if init.capabilities.resources else None
     templates=await s.list_resource_templates() if init.capabilities.resources else None
     await s.send_ping()
     return {'initialize':init.model_dump(mode='json',by_alias=True),'tools':tools.model_dump(mode='json',by_alias=True),'prompts':prompts.model_dump(mode='json',by_alias=True) if prompts else None,'resources':resources.model_dump(mode='json',by_alias=True) if resources else None,'templates':templates.model_dump(mode='json',by_alias=True) if templates else None,'ping':'passed','api_key_used':False}
    if command=='resource':
     resources=await s.list_resources();uris={str(r.uri) for r in resources.resources}
     if name not in uris:raise ValueError('Можно читать только опубликованные ресурсы Scholar Sidekick.')
     return (await s.read_resource(name)).model_dump(mode='json',by_alias=True)
    if command=='prompt':
     listing=await s.list_prompts()
     if name not in {p.name for p in listing.prompts}:raise ValueError('Шаблон отсутствует в каталоге.')
     return (await s.get_prompt(name,arguments=args)).model_dump(mode='json',by_alias=True)
    calls=args if command=='batch' else [{'name':name,'arguments':args}]
    if not isinstance(calls,list) or not 1<=len(calls)<=12:raise ValueError('Не более 12 явных операций за одну команду.')
    prepared=[]
    for c in calls:
     n=c['name'];a=c.get('arguments',{})
     if n not in catalog:raise ValueError('Метод отсутствует в живом каталоге.')
     jsonschema.Draft7Validator(catalog[n].input_schema).validate(a)
     if a.get('screenWithLlm'):raise ValueError('Проверка языковой моделью требует отдельного ключа; сейчас выбран анонимный режим.')
     prepared.append((n,a))
    results=[]
    for n,a in prepared:
     await asyncio.to_thread(pace,mcp_group(n));r=await s.call_tool(n,arguments=a);dump=r.model_dump(mode='json',by_alias=True)
     results.append({'name':n,'arguments':a,'result':dump})
     if r.is_error:break
    return results[0]['result'] if command=='call' else {'ok':not any(x['result'].get('isError') for x in results),'calls':results,'api_key_used':False}

def json_value(v):
 if dataclasses.is_dataclass(v):return dataclasses.asdict(v)
 if isinstance(v,(str,list,dict,int,float,bool)) or v is None:return v
 if hasattr(v,'model_dump'):return v.model_dump(mode='json')
 raise ValueError('Неизвестный формат результата официального клиента.')

def normalize_supplied_items(items):
 """Translate standard CSL fields to the production route's Biblio shape.

 Keep the original fields and original CSL object; never fill metadata from memory.
 """
 out=[];changed=False
 for item in items:
  if 'author' not in item and 'date-parts' not in (item.get('issued') or {}):out.append(item);continue
  changed=True;n=dict(item);n['_provided_csl']=dict(item)
  n['type']={'article-journal':'journal-article','chapter':'book-chapter','paper-conference':'conference-paper'}.get(item.get('type'),item.get('type'))
  if 'author' in item:n['authors']=item['author']
  container=dict(item.get('container') or {})
  for src,dst in [('container-title','title'),('container-title-short','abbreviated'),('volume','volume'),('issue','issue')]:
   if src in item:container[dst]=item[src]
  n['container']=container
  parts=(item.get('issued') or {}).get('date-parts') or []
  if parts:
   n['issued']={k:v for k,v in zip(['year','month','day'],parts[0])}
  ids=[]
  for key in ['DOI','PMID','PMCID','ISBN','ISSN']:
   values=item.get(key)
   for value in values if isinstance(values,list) else [values] if values else []:ids.append({'type':key.lower(),'value':str(value)})
  if ids:n['identifiers']=ids
  if 'URL' in item:n['url']=item['URL']
  if 'page' in item:
   import re
   pages=re.split(r'[-–]',str(item['page']),maxsplit=1);n['pages']={'first':pages[0],**({'last':pages[1]} if len(pages)>1 else {})}
  if 'article-number' in item:n['number']=item['article-number']
  out.append(n)
 return out,changed

def rest(name,args):
 # Empty explicit key disables environment fallback in official SDK 0.1.0.
 # Never forward ambient RapidAPI, first-party keys, or host overrides.
 typed={'format','format_items','export','verify','audit','audit_bibliography','health'}
 if name in typed:
  args=dict(args);compatibility=None
  if name=='format_items':
   args['items'],changed=normalize_supplied_items(args['items'])
   if changed:compatibility='Standard CSL author/date-parts/container-title normalized for current production Biblio renderer; metadata is owner-supplied and not independently verified.'
  pace('format' if name in {'format','format_items','export'} else 'audit' if name.startswith('audit') else 'other')
  with ScholarSidekick(api_key='',base_url=BASE,timeout=120,connect_timeout=15,max_retries=0) as client:
   return {'ok':True,'operation':name,'provider':'Scholar Sidekick official Python SDK 0.1.0','api_key_used':False,'data':json_value(getattr(client,name)(**args)),'compatibility':compatibility}
 routes={'detect':('/api/detect','POST'),'lookup':('/api/lookup','POST'),'styles':('/api/csl/styles','GET'),'stream':('/api/format/stream','POST')}
 if name not in routes:raise ValueError('Неизвестная операция прямого API.')
 path,method=routes[name];spec=load(P/'источники/openapi.json');op=spec['paths'][path][method.lower()]
 if method=='POST':
  schema=op['requestBody']['content']['application/json']['schema']
  jsonschema.Draft202012Validator(schema,resolver=jsonschema.RefResolver.from_schema(spec)).validate(args)
 else:
  allowed={'q','category','bundled','limit','offset','remote','categories'}
  if set(args)-allowed:raise ValueError('Неизвестный параметр поиска стилей.')
  if int(args.get('limit',20))>200:raise ValueError('Для обзора выберите до 200 стилей за страницу.')
 pace('format' if name=='stream' else 'other')
 query={k:('true' if v else 'false') if isinstance(v,bool) else v for k,v in args.items()}
 body=args
 compatibility=None
 if name=='stream':
  # Published OpenAPI accepts lines, but the current production route requires text.
  body={'text':'\n'.join(args['lines']),'style':args.get('style','vancouver')}
  compatibility='OpenAPI lines[] converted to production text; diagnosed by VALIDATION_ERROR on 2026-10-07.'
 response=requests.request(method,BASE+path,params=query if method=='GET' else None,json=body if method=='POST' else None,headers={'Accept':'application/x-ndjson' if name=='stream' else 'application/json','User-Agent':'HermesBN-ScholarSidekick/1.0'},timeout=(15,180),allow_redirects=False)
 headers={k:v for k,v in response.headers.items() if k.lower().startswith(('x-ratelimit','ratelimit','x-scholar','x-request','x-error')) or k.lower() in {'retry-after','content-type'}}
 if response.status_code!=200:
  try:details=response.json()
  except ValueError:details={'body_excerpt':response.text[:1500]}
  return {'ok':False,'operation':name,'http_status':response.status_code,'headers':headers,'api_key_used':False,'error_details':details,'error':'Операция не выполнена; повтор или смена службы не выполняются автоматически.'}
 data=[json.loads(line) for line in response.text.splitlines() if line.strip()] if name=='stream' else response.json()
 return {'ok':True,'operation':name,'http_status':response.status_code,'provider':'Scholar Sidekick documented REST API','api_key_used':False,'headers':headers,'data':data,'compatibility':compatibility}
