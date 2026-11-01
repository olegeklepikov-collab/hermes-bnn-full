"""Semantic Scholar's official public APIs, isolated for Hermes BN."""
import fcntl,html,json,os,re,time,uuid
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import quote,unquote
import requests
from dotenv import dotenv_values
from jsonschema import Draft7Validator
ROOT=Path(__file__).resolve().parent
HOST='https://api.semanticscholar.org'
NAMES={'post_graph_get_authors':'author_batch','get_graph_get_author_search':'author_search','get_graph_get_author':'author_details','get_graph_get_author_papers':'author_papers','get_graph_get_paper_autocomplete':'paper_autocomplete','post_graph_get_papers':'paper_batch','get_graph_paper_relevance_search':'paper_search','get_graph_paper_bulk_search':'paper_bulk_search','get_graph_paper_title_search':'paper_match_title','get_graph_get_paper':'paper_details','get_graph_get_paper_authors':'paper_authors','get_graph_get_paper_citations':'paper_citations','get_graph_get_paper_references':'paper_references','get_snippet_search':'snippet_search','post_papers':'recommend_by_examples','get_papers_for_paper':'recommend_for_paper','get_diff':'dataset_diffs','get_releases':'dataset_releases','get_release':'dataset_release','get_dataset':'dataset_manifest'}
PAPER_FIELDS='paperId,corpusId,title,authors,year,publicationDate,externalIds,url,venue,publicationTypes,isOpenAccess,openAccessPdf,citationCount,referenceCount,influentialCitationCount'
AUTHOR_FIELDS='authorId,name,url,affiliations,paperCount,citationCount,hIndex'


def resolve(value,spec):
 if isinstance(value,list):return [resolve(v,spec) for v in value]
 if not isinstance(value,dict):return value
 if '$ref' in value:
  node=spec
  for part in value['$ref'].lstrip('#/').split('/'):
   decoded=unquote(part).replace('~1','/').replace('~0','~');node=node[decoded if decoded in node else part]
  return resolve(node,spec)
 return {k:resolve(v,spec) for k,v in value.items() if k not in {'example','xml','discriminator'}}

def plain(s):return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]*>',' ',s))).strip()

def catalog():
 out={}
 for service in ['graph','recommendations','datasets']:
  spec=json.loads((ROOT/f'источники/{service}-openapi.json').read_text())
  for path,item in spec['paths'].items():
   for verb,op in item.items():
    if verb not in {'get','post'}:continue
    name=NAMES[op['operationId']];props={};required=[];params=[];body=[]
    for raw in item.get('parameters',[])+op.get('parameters',[]):
     p=resolve(raw,spec);params.append(p)
     if p['in']=='body':
      schema=resolve(p['schema'],spec);props.update(schema.get('properties',{}));body=list(schema.get('properties',{}));required+=schema.get('required',[])
     else:
      props[p['name']]={k:v for k,v in p.items() if k in {'type','enum','default','minimum','maximum','minLength','maxLength','items','pattern'}}
      props[p['name']]['description']=plain(p.get('description',''))[:1800]
      if p.get('required'):required.append(p['name'])
    if name in {'paper_batch','author_batch'}:
     required.append('ids');props['ids'].update(minItems=1,maxItems=500 if name=='paper_batch' else 1000)
    if name=='recommend_by_examples':required.append('positivePaperIds');props['positivePaperIds']['minItems']=1
    for k in ['offset','limit']:
     if k in props:props[k]['minimum']=0 if k=='offset' else 1
    if 'limit' in props and 'maximum' not in props['limit']:props['limit']['maximum']=1000
    defaults={}
    if 'limit' in props:defaults['limit']=10
    if 'fields' in props:
     defaults['fields']='snippet.text,snippet.snippetKind,snippet.section,snippet.snippetOffset' if name=='snippet_search' else AUTHOR_FIELDS if name in {'author_search','author_details','author_batch','paper_authors'} else PAPER_FIELDS
    out[name]={'name':name,'summary':op.get('summary',''),'description':plain(op.get('description','')),'service':service,'verb':verb.upper(),'base':spec.get('basePath',f'/{service}/v1'),'path':path,'parameters':params,'body_properties':body,'defaults':defaults,'input_schema':{'type':'object','properties':props,'required':list(dict.fromkeys(required)),'additionalProperties':False}}
 return out

OPERATIONS=catalog()

def credentials():
 path=ROOT/'credentials.env'
 if path.exists() and path.stat().st_mode & 0o077:raise ValueError('Файл credentials.env должен иметь права 0600.')
 key=dotenv_values(path,interpolate=False).get('SEMANTIC_SCHOLAR_API_KEY') if path.exists() else None
 if key and re.search(r'[\s\x00-\x1f\x7f]',str(key).strip()):raise ValueError('Ключ содержит недопустимые символы.')
 return str(key).strip() if key else None

def status():
 return {'service':'Semantic Scholar','official_api_host':HOST,'api_key_saved':bool(credentials()),'credential_file':str(ROOT/'credentials.env'),'operations':len(OPERATIONS),'request_interval_seconds':1.1,'rate_scope':'all API families and processes of this instance','datasets_files_downloaded':False,'mode':'authenticated' if credentials() else 'public_without_key','availability':'public shared rate limits; availability varies by operation','temporary_hold':temporary_hold()}

def temporary_hold():
 path=ROOT/'config/temporary-hold.json'
 return json.loads(path.read_text()) if path.exists() else {'active':False}

def paced_request(method,url,query,body,key):
 lock=ROOT/'config/request.lock';last=ROOT/'config/last-request.txt';lock.parent.mkdir(exist_ok=True)
 with lock.open('a+') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX)
  previous=float(last.read_text()) if last.exists() else 0
  delay=1.1-(time.time()-previous)
  if delay>0:time.sleep(delay)
  last.write_text(str(time.time()))
  headers={'Accept':'application/json','User-Agent':'Hermes-BN-SemanticScholar/1.0'}
  if key:headers['x-api-key']=key
  return requests.request(method,url,params=query,json=body,headers=headers,timeout=(10,35),allow_redirects=False)

def redact_download_links(value):
 if isinstance(value,list):return [redact_download_links(x) for x in value]
 if isinstance(value,dict):
  out={}
  for k,v in value.items():
   if k in {'files','update_files','delete_files'} and isinstance(v,list):out[k+'_count']=len(v);out[k+'_hidden']=True
   else:out[k]=redact_download_links(v)
  return out
 return value

def call(name,arguments):
 if name not in OPERATIONS:raise ValueError('Неизвестная операция: '+name)
 hold=temporary_hold()
 if hold.get('active') and name in hold.get('blocked_methods',[]):
  return {'ok':False,'service':'Semantic Scholar','operation':name,'state':'pending_external_decision','error_code':'temporary_hold','message':hold['reason'],'network_request_performed':False,'http_status':None,'api_key_used':False,'retry_allowed':False,'action':'Не повторять заявку и недоступный запрос. Дождаться решения и отдельного поручения о снятии заглушки.','resume_conditions':hold['resume_conditions']}
 op=OPERATIONS[name];args={**op['defaults'],**arguments};errors=list(Draft7Validator(op['input_schema']).iter_errors(args))
 if errors:raise ValueError('; '.join(e.message for e in errors[:3]))
 path=op['path'];query={};body={k:args[k] for k in op['body_properties'] if k in args} or None
 for param in op['parameters']:
  k=param['name']
  if k not in args:continue
  if param['in']=='path':path=path.replace('{'+k+'}',quote(str(args[k]),safe=''))
  elif param['in']=='query':query[k]=args[k]
 key=credentials();url=HOST+op['base']+path;r=None;attempts=0
 for attempt in range(2):
  r=paced_request(op['verb'],url,query,body,key);attempts+=1
  if r.status_code not in {429,502,503,504}:break
  value=r.headers.get('Retry-After');delay=5
  if value:
   try:delay=max(0,float(value))
   except ValueError:
    from email.utils import parsedate_to_datetime
    try:delay=max(0,parsedate_to_datetime(value).timestamp()-time.time())
    except (ValueError,TypeError):delay=5
  if delay>30 or attempt==1:break
  time.sleep(delay)
 try:data=r.json()
 except ValueError:data={'message':'Ответ не содержит JSON.'}
 result={'ok':r.ok,'service':'Semantic Scholar','operation':name,'api_key_used':bool(key),'http_status':r.status_code,'attempts':attempts,'retrieved_at':datetime.now(ZoneInfo('Asia/Dubai')).isoformat(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'request':{'method':op['verb'],'path':op['base']+path,'parameters':args},'data':data}
 if key:
  encoded=json.dumps(result,ensure_ascii=False).replace(key,'[скрыто]');result=json.loads(encoded)
 if r.status_code==429:result['retry_after']=r.headers.get('Retry-After');result['action']='Соблюсти ограничение; получить отдельный ключ при анонимном доступе.'
 if name in {'dataset_manifest','dataset_diffs'}:
  raw=ROOT/'checks'/('dataset-response-'+uuid.uuid4().hex+'.json');raw.parent.mkdir(exist_ok=True);raw.write_text(json.dumps(result,ensure_ascii=False,indent=2));raw.chmod(0o600);result['data']=redact_download_links(result['data']);result['private_raw_file']=str(raw);result['note']='Временные ссылки скрыты в ответе агента. Файлы не скачивались; условия каждого набора проверяются отдельно.'
 audit=ROOT/'checks/request-log.jsonl';audit.parent.mkdir(exist_ok=True)
 with audit.open('a') as f:f.write(json.dumps({k:v for k,v in result.items() if k not in {'data','request'}},ensure_ascii=False)+'\n')
 audit.chmod(0o600)
 return result
