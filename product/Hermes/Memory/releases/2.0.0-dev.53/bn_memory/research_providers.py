"""Pinned read-only provider clients behind the existing final native RPC admission."""
import hashlib,json,os,re,stat,time
from pathlib import Path
from urllib.parse import urlsplit
from bn_memory.store import canonical,sha

PROVIDERS={'exa':'https://api.exa.ai','parallel':'https://api.parallel.ai','keenable':'https://api.keenable.ai','firecrawl':'https://api.firecrawl.dev'}
MAX_BYTES=8*1024*1024

def schemas():
    out={}
    for provider in PROVIDERS:
        common={'request_id':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,96}$'},'offset':{'type':'integer','minimum':0},'page_chars':{'type':'integer','minimum':1,'maximum':8192}}
        out[provider+'_search']=(provider+': официальный поиск. Точный поставщик без подмены. Полный ответ сохранён; страницы до next_offset=null. Повтор с тем же request_id и вводом читает сохранённый ответ; неизвестный исход не повторяется. Выдача и отрывки не означают чтение полной статьи.',{**common,'query':{'type':'string','minLength':1,'maxLength':2000},'limit':{'type':'integer','minimum':1,'maximum':10}},['query','request_id'])
        out[provider+'_fetch']=(provider+': извлечение публичной страницы официальным API. Без команд, входа в сайты, публикации и автоматических повторов. Прочитай все страницы до next_offset=null; отсутствие текста явно видно.',{**common,'url':{'type':'string','minLength':1,'maxLength':2048}},['url','request_id'])
    return out

def request_spec(provider,operation,args):
    base=PROVIDERS[provider]
    if operation=='search':
        q=args['query'];n=args.get('limit',2)
        values={'exa':('/search',{'query':q,'numResults':n,'type':'auto'}),'parallel':('/v1/search',{'objective':q,'search_queries':[q],'mode':'basic','max_chars_total':8000}),
                'keenable':('/v1/search',{'query':q,'max_results':n}),'firecrawl':('/v2/search',{'query':q,'limit':n,'sources':['web']})}
        path,payload=values[provider];return 'POST',base+path,payload
    url=args['url']
    values={'exa':('/contents',{'urls':[url],'text':True}),'parallel':('/v1/extract',{'urls':[url],'max_chars_total':8000}),
            'keenable':('/v1/fetch',{'url':url}),'firecrawl':('/v2/scrape',{'url':url,'formats':['markdown']})}
    path,payload=values[provider];return ('GET' if provider=='keenable' else 'POST'),base+path,payload

def key_identity(path):
    p=Path(path);s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_nlink!=1:raise PermissionError('provider_credential_permissions_invalid')
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_uid,s.st_mode]

def resource_hash(config,provider):
    entry=config['research_providers']['providers'][provider]
    return sha(canonical({'provider':provider,'endpoint':PROVIDERS[provider],'key_path':entry['key_file'],'key_identity':key_identity(entry['key_file']),
        'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'namespace':config['namespace'],'profile_home':config['profile_home'],'state_root':config['state_root']}))

def page(body,args,receipt):
    start=args.get('offset',0);size=args.get('page_chars',8192)
    if type(start) is not int or type(size) is not int or not 0<=start<=len(body) or not 1<=size<=8192:raise ValueError('provider_page_invalid')
    end=min(start+size,len(body));part=body[start:end]
    value={**receipt,'text':part,'offset':start,'next_offset':end if end<len(body) else None,'complete':end==len(body),
        'total_characters':len(body),'response_sha256':sha(body),'fragment_sha256':sha(part),'reading_level':'provider_response_page_unreviewed','article_full_text_read':False}
    if start==0 and end==len(body):value['data']=json.loads(body)
    return value

def fetch_once(provider,operation,args,key):
    import requests
    method,url,payload=request_spec(provider,operation,args)
    header='Authorization' if provider=='firecrawl' else 'X-API-Key'
    headers={header:'Bearer '+key if provider=='firecrawl' else key,'Content-Type':'application/json','User-Agent':'Hermes-BNN-research/1.0'}
    started=time.monotonic()
    with requests.Session() as client:
        client.trust_env=False
        with client.request(method,url,params=payload if method=='GET' else None,json=payload if method=='POST' else None,
                            headers=headers,timeout=(10,45),allow_redirects=False,stream=True) as response:
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>MAX_BYTES or time.monotonic()-started>90:raise RuntimeError('provider_response_bound_unknown_no_automatic_retry')
                chunks.append(chunk)
            raw=b''.join(chunks)
            if key.encode() in raw:raise PermissionError('provider_echoed_credential_response_withheld')
            body=raw.decode('utf-8');json.loads(body)
            return body,{'provider':provider,'operation':operation,'endpoint':url,'http_status':response.status_code,'authenticated':True,
                         'credential_disclosed':False,'provider_substitution':False,'elapsed_seconds':round(time.monotonic()-started,3)}

def dispatch(broker,sid,name,args):
    from jsonschema import Draft202012Validator
    from bn_memory.write_origin import for_binding
    from bn_memory.artifacts import Artifacts
    binding=broker.store.binding(sid);origin=for_binding(binding)
    if not origin.get('attempt_id'):raise PermissionError('provider_final_native_origin_required')
    name_schema=schemas().get(name)
    if name_schema is None:raise ValueError('provider_operation_not_supported')
    _,properties,required=name_schema;clean={k:v for k,v in args.items() if k not in {'_host','_runtime'}}
    Draft202012Validator({'type':'object','properties':properties,'required':required,'additionalProperties':False}).validate(clean)
    provider,operation=name.split('_',1);cfg=broker.config;entry=cfg['research_providers']['providers'][provider]
    if entry['resource_sha256']!=resource_hash(cfg,provider):raise PermissionError('provider_resource_changed_reapproval_required')
    guard=Artifacts(broker);guard.sensitive(canonical(clean).encode(),guard.secrets())
    if operation=='fetch':
        from tools.url_safety import is_safe_url
        url=urlsplit(clean['url'])
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or not is_safe_url(clean['url']):raise PermissionError('public_https_provider_source_required')
    key=Path(entry['key_file']).read_text().strip()
    query={k:v for k,v in clean.items() if k not in {'request_id','offset','page_chars'}};basis=sha(canonical([name,query]));rid=clean['request_id']
    with broker.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS provider_requests(profile_id TEXT,sid TEXT,request_id TEXT,basis TEXT,state TEXT,body TEXT,receipt TEXT,PRIMARY KEY(profile_id,sid,request_id))')
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM provider_requests WHERE profile_id=? AND sid=? AND request_id=?',(broker.store.profile,sid,rid)).fetchone()
        if row:
            if row['basis']!=basis:raise PermissionError('provider_request_id_conflict')
            if row['state']!='returned':raise PermissionError('provider_outcome_unknown_no_automatic_retry')
            return page(row['body'],clean,{**json.loads(row['receipt']),'cached':True,'new_remote_requests':0})
        if clean.get('offset',0)!=0:raise PermissionError('first_provider_page_required')
        db.execute('INSERT INTO provider_requests VALUES(?,?,?,?,?,?,?)',(broker.store.profile,sid,rid,basis,'outcome_unknown',None,None))
    body,receipt=fetch_once(provider,operation,clean,key)
    guard.sensitive(body.encode(),guard.secrets())
    with broker.store.db() as db:db.execute("UPDATE provider_requests SET state='returned',body=?,receipt=? WHERE profile_id=? AND sid=? AND request_id=?",(body,canonical(receipt),broker.store.profile,sid,rid))
    return page(body,clean,{**receipt,'cached':False,'new_remote_requests':1})
