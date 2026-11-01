"""One confined MCP session, exact pinned declaration, no sampling/delegation callbacks."""
from pathlib import Path
from contextlib import AsyncExitStack
import asyncio,json,os
from bn_memory.store import canonical,sha

async def call(config,entry,name,args,_queue=None,_ready=None):
 from mcp import ClientSession,StdioServerParameters
 from mcp.client.stdio import stdio_client
 from mcp.client.streamable_http import streamable_http_client
 import httpx2
 from bn_memory.service_engine import read_catalog
 root=Path(config['profile_home']).parent
 secret=json.loads(Path(entry['authority_file']).read_text())
 method=read_catalog(config)['services'][entry['service']]['methods'].get(name,{})
 if method.get('builtin')=='r_cran_versions':
  from bn_memory.service_r_versions import call as versions
  return await asyncio.wait_for(asyncio.to_thread(versions,args),timeout=90)
 if method.get('api_request'):
  return await asyncio.wait_for(asyncio.to_thread(rest_call,entry,method,args,secret),timeout=240)
 initial_name,initial_args=name,args
 async def actual():
  async with AsyncExitStack() as stack:
   if entry['transport']=='http':
    auth=None
    if entry.get('authentication')=='independent_BNN_oauth':
     from tools.mcp_oauth_manager import get_manager
     auth=get_manager().get_or_build_provider(entry['service'],entry['url'],entry.get('oauth'))
     if auth is None:raise PermissionError('independent_service_oauth_unavailable')
    http=await stack.enter_async_context(httpx2.AsyncClient(headers=secret['headers'],auth=auth,timeout=180,trust_env=False,follow_redirects=False))
    streams=await stack.enter_async_context(streamable_http_client(entry['url'],http_client=http))
   else:
    env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','SSL_CERT_FILE'}}
    env.update(entry['env']);env['HERMES_BNN_SERVICES_AUTH']=str(Path(entry['authority_file']).parent)
    # Secrets are per service; never inherit the parent's environment or other keys.
    state=entry.get('_runtime_state_root',entry['state_root']);Path(state).mkdir(parents=True,exist_ok=True)
    env.update(secret['env']);env['HOME']=state
    if entry.get('untrusted_evaluator'):env['HERMES_BN_R_HOME']=state
    tmp=Path(state)/'.tmp';tmp.mkdir(exist_ok=True);env['TMPDIR']=str(tmp);env['XDG_CACHE_HOME']=str(tmp)
    from bn_memory.service_sandbox import profile
    sandbox=profile(root,entry,entry.get('_policy_method',initial_name))
    log=(Path(config['state_root'])/'service-transport-errors.log').open('a');stack.callback(log.close)
    streams=await stack.enter_async_context(stdio_client(StdioServerParameters(command='/usr/bin/sandbox-exec',args=['-p',sandbox,entry['command'],*entry['args']],env=env,cwd=state),errlog=log))
   session=await stack.enter_async_context(ClientSession(streams[0],streams[1]))
   await session.initialize();listing=await session.list_tools();catalogue={t.name:t for t in listing.tools};cursor=listing.next_cursor
   while cursor:
    listing=await session.list_tools(cursor=cursor);catalogue.update({t.name:t for t in listing.tools});cursor=listing.next_cursor
   import uuid
   peer_id='MCP-'+uuid.uuid4().hex
   if _ready is not None and not _ready.done():_ready.set_result(True)
   while True:
    if _queue is not None:
     item=await _queue.get()
     if item is None:return
     name,args,future,request_entry=item
    else:name,args=initial_name,initial_args;request_entry=entry
    try:
     expected=read_catalog(config)['services'][entry['service']]['methods'][name]
     if name not in catalogue or sha(canonical(catalogue[name].input_schema))!=expected['schema_sha256']:raise PermissionError('service_live_schema_changed_requires_operator_review')
     effective=dict(args)
     if entry.get('untrusted_evaluator') and name=='btw_tool_run_r':
      files=request_entry.get('_input_snapshots',[]);pairs=[]
      for f in files:
       pairs.append(json.dumps(f['path'],ensure_ascii=False)+'='+json.dumps(f['path'],ensure_ascii=False))
       if f.get('requested_path') and f['requested_path']!=f['path']:pairs.append(json.dumps(f['requested_path'],ensure_ascii=False)+'='+json.dumps(f['path'],ensure_ascii=False))
       if sum(Path(x['path']).name==Path(f['path']).name for x in files)==1:pairs.append(json.dumps(Path(f['path']).name,ensure_ascii=False)+'='+json.dumps(f['path'],ensure_ascii=False))
      preamble='graphics::par(bg="white")\nINPUT_FILES <- '+('c('+','.join(pairs)+')' if pairs else 'setNames(character(),character())')+'\n'
      effective['code']=preamble+args['code']
     value=await asyncio.wait_for(session.call_tool(name,arguments=effective),timeout=entry.get('tool_timeout',180))
     result=value.model_dump(mode='json',by_alias=True)
     result.pop('_bnn_file_receipts',None)
     if entry['transport']=='stdio':
      # A legacy preview is not the complete provider result. Capture the actual
      # preserved file only inside this executor's own output scope.
      spillovers=[];files=[]
      owned=[Path(entry['state_root'])/x for x in ['exports','downloads','content','cache','data','results','stream-results']]
      if entry.get('_runtime_state_root'):owned.append(Path(entry['_runtime_state_root']))
      if entry['service']=='zotero':owned.append(Path(config['zotero_root'])/'data')
      def file_receipt(path):
       p=Path(path)
       if not p.is_file() or p.is_symlink():return
       target=p.resolve()
       if not any(target.is_relative_to(root.resolve()) for root in owned):return
       if any(x.is_symlink() for x in p.parents if x!=Path('/')):return
       raw=target.read_bytes();files.append({'path':str(target),'bytes':len(raw),'sha256':__import__('hashlib').sha256(raw).hexdigest()})
      def inspect(v):
       if isinstance(v,dict):
        if isinstance(v.get('complete_result_file'),str):
         p=Path(v['complete_result_file']);target=p.resolve(strict=True)
         allowed=[Path(entry['state_root']).resolve(),Path(entry.get('_runtime_state_root',entry['state_root'])).resolve()]
         if p.is_symlink() or not any(target.is_relative_to(root) for root in allowed):raise PermissionError('legacy_result_file_outside_executor_scope')
         raw=target.read_bytes();spillovers.append({'file':str(target),'source_bytes_sha256':__import__('hashlib').sha256(raw).hexdigest(),'text':raw.decode('utf-8'),'complete_preserved_file':True})
        for key,item in v.items():
         if isinstance(item,str) and item.startswith('/') and any(x in key.lower() for x in ['file','path','output','export']):file_receipt(item)
         inspect(item)
       elif isinstance(v,list):
        for item in v:inspect(item)
      for content in result.get('content',[]):
       if content.get('type')=='text':
        try:inspect(json.loads(content['text']))
        except json.JSONDecodeError:pass
      if spillovers:result['materialized_legacy_spillovers']=spillovers
      if files:result['_bnn_file_receipts']=list({x['path']:x for x in files}.values())
     result['bnn_transport']={'effective_arguments_sha256':sha(canonical(effective)),'peer_id':peer_id,'persistent_per_native_session':_queue is not None}
     if _queue is None:return result
     if not future.done():future.set_result(result)
    except BaseException as exc:
     if _queue is None:raise
     if not future.done():future.set_exception(exc)
     if isinstance(exc,asyncio.CancelledError):raise

 return await actual() if _queue is not None else await asyncio.wait_for(actual(),timeout=240)

def rest_call(entry,method,args,secret):
 from urllib.parse import quote,urlsplit
 import requests,base64,time
 request=method['api_request'];path=request['path'];headers={}
 for key,value in args.get('path',{}).items():path=path.replace('{'+key+'}',quote(str(value),safe=''))
 if re_unfilled(path):raise ValueError('documented_path_parameter_missing')
 service=entry['service'];original=secret['headers'];key=original.get('x-api-key',original.get('X-API-Key',original.get('Authorization','')))
 if key.startswith('Bearer '):key=key[7:]
 if service=='tavily':key=secret['env'].get('TAVILY_API_KEY','')
 if not key and service not in {'datacite','synapse'}:raise PermissionError('service_api_credential_required')
 if key:headers[{'exa':'x-api-key','keenable':'X-API-Key','parallel-task':'x-api-key','tinyfish-api':'X-API-Key'}.get(service,'Authorization')]=key if service in {'exa','keenable','parallel-task','tinyfish-api'} else 'Bearer '+key
 for k,v in args.get('header',{}).items():
  if k.lower() in {'authorization','x-api-key','cookie','host','content-type'} or any(x in str(v) for x in ['\r','\n']):raise PermissionError('unsafe_service_header')
  headers[k]=str(v)
 headers['User-Agent']='Hermes-BNN-Services/1.0';headers['Content-Type']='application/json'
 query=[]
 for param in request['parameters'].get('query',[]):
  n=param['name']
  if n not in args.get('query',{}):continue
  value=args['query'][n]
  if isinstance(value,list):
   if param.get('explode',True):query.extend((n,str(v).lower() if isinstance(v,bool) else str(v)) for v in value)
   else:query.append((n,','.join(map(str,value))))
  else:query.append((n,str(value).lower() if isinstance(value,bool) else str(value)))
 url=request['base']+path
 allowed={'firecrawl':{'api.firecrawl.dev'},'exa':{'api.exa.ai'},'tavily':{'api.tavily.com'},'keenable':{'api.keenable.ai'},'nimble':{'sdk.nimbleway.com'},'parallel-task':{'api.parallel.ai'},'datacite':{'api.datacite.org'},'synapse':{'repo-prod.prod.sagebase.org'},'tinyfish-api':{'agent.tinyfish.ai','api.search.tinyfish.ai','api.fetch.tinyfish.ai','api.browser.tinyfish.ai'},'elicit-api':{'elicit.com'}}
 if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in allowed[service]:raise PermissionError('service_api_endpoint_pin_mismatch')
 with requests.Session() as client:
  client.trust_env=False
  begin=time.monotonic()
  with client.request(request['method'],url,params=query,json=args.get('body'),headers=headers,timeout=(10,30),allow_redirects=False,stream=True) as response:
   # Finite JSON HTTP endpoints only. SSE endpoints are catalogued but not granted.
   if 'text/event-stream' in response.headers.get('content-type',''):raise RuntimeError('supervised_event_stream_adapter_required')
   parts=[];size=0
   for part in response.iter_content(65536):
    size+=len(part)
    if size>128*1024*1024 or time.monotonic()-begin>180:raise RuntimeError('service_response_requires_provider_pagination_no_truncated_success')
    parts.append(part)
   raw=b''.join(parts)
   if key and key.encode() in raw:raise PermissionError('service_credential_echo_response_withheld')
   try:data=json.loads(raw)
   except ValueError:
    try:data={'text':raw.decode('utf-8')}
    except UnicodeDecodeError:data={'base64':base64.b64encode(raw).decode(),'binary_reading_level':'downloaded_bytes_not_document_read'}
   return {'isError':not 200<=response.status_code<300,'http_status':response.status_code,'endpoint':url,'response_bytes_sha256':__import__('hashlib').sha256(raw).hexdigest(),'content_type':response.headers.get('content-type'),'data':data,'rate_limit':{k:v for k,v in response.headers.items() if 'ratelimit' in k.lower() or k.lower()=='retry-after'},'automatic_retry':False}
def re_unfilled(path):return '{' in path or '}' in path
