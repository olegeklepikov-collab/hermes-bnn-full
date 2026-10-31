"""Complete published OpenAPI surfaces; no guessed endpoint or caller-supplied host."""
from pathlib import Path
import copy,hashlib,json,re
import yaml
from service_docs import BASE
SPECS={
 'firecrawl':'https://docs.firecrawl.dev/api-reference/v2-openapi.json',
 'exa':'https://exa.ai/docs/exa-spec.json',
 'tavily':'https://docs.tavily.com/documentation/api-reference/openapi.json',
 'nimble':'https://docs.nimbleway.com/api-reference/openapi.json',
 'parallel-task':'https://docs.parallel.ai/docs-latest-openapi.json',
 'keenable':'https://docs.keenable.ai/api-reference/search-api.json',
}
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(v.encode()).hexdigest()
def convert_nullable(value):
 if isinstance(value,list):return [convert_nullable(x) for x in value]
 if not isinstance(value,dict):return value
 v={k:convert_nullable(x) for k,x in value.items() if k not in {'nullable','example','xml','discriminator'}}
 if value.get('nullable'):return {'anyOf':[v,{'type':'null'}]}
 return v
def local_ref(spec,value):
 if '$ref' not in value:return value
 ref=value['$ref']
 if not ref.startswith('#/'):raise ValueError('external_openapi_reference_requires_pinned_source')
 out=spec
 for key in ref[2:].split('/'):out=out[key.replace('~1','/').replace('~0','~')]
 return {**out,**{k:v for k,v in value.items() if k!='$ref'}}
def close_references(schema,spec):
 """Retain every reachable schema dependency, without copying unrelated components."""
 result=copy.deepcopy(schema);pending=[schema];seen=set()
 def references(value):
  if isinstance(value,dict):
   if isinstance(value.get('$ref'),str):yield value['$ref']
   for x in value.values():yield from references(x)
  elif isinstance(value,list):
   for x in value:yield from references(x)
 while pending:
  value=pending.pop()
  for ref in references(value):
   if ref in seen:continue
   seen.add(ref)
   if not ref.startswith('#/'):raise ValueError('unresolved_external_schema_reference')
   tokens=[s.replace('~1','/').replace('~0','~') for s in ref[2:].split('/')];source=spec
   for token in tokens:source=source[token]
   target=result
   for token in tokens[:-1]:target=target.setdefault(token,{})
   target[tokens[-1]]=copy.deepcopy(source);pending.append(source)
 return result
def effect(service,verb,path):
 p=path.lower()
 if any(x in p for x in ['/feedback','/threat-protection','/support/ask','/chat/completions','/responses','/webhooks','/v0/imports']):return 'blocked'
 if p.endswith('/events') or '/events/' in p or '/snapshots/' in p:return 'blocked'
 if verb=='get':return 'read'
 if verb in {'delete','patch','put'}:return 'write'
 if any(x in p for x in ['/cancel','/stop','/update','/clear','/evict','/ingest']):return 'write'
 if service=='firecrawl':
  if path in ['/scrape','/map','/search','/parse','/crawl/params-preview','/support/docs-search','/search/developer','/search/gov']:return 'read'
  if path in ['/crawl','/batch/scrape','/extract','/agent'] or path.endswith('/run'):return 'job'
  return 'write'
 if service=='exa':
  if path in ['/search','/contents','/answer','/findSimilar','/v0/websets/preview']:return 'read'
  if path in ['/agent/runs','/batches','/v0/websets'] or '/searches' in p or '/enrichments' in p or path.endswith('/trigger'):return 'job'
  return 'write'
 if service=='tavily':return 'job' if path=='/research' else 'read'
 if service=='keenable':return 'read'
 if service=='nimble':
  if path in ['/v2/search','/v2/extract','/v2/map','/v2/serp','/v1/realtime/serp','/v2/extract/templates/run','/v2/media','/v1/domain-health/check']:return 'read'
  if any(x in p for x in ['/async','/batch','/runs']) or path in ['/v2/crawl','/v2/jobs','/v2/extract/templates/generations']:return 'job'
  return 'write'
 if service=='parallel-task':
  if path in ['/v1/search','/v1/images/search','/v1/extract','/v1/decisions','/v1beta/findall/entity-search','/v1beta/memory/retrieve']:return 'read'
  if '/findall/runs' in p or '/tasks/' in p or p.endswith('/trigger'):return 'job'
  return 'write'
 return 'blocked'
def augment(catalogue):
 ledger=json.loads((BASE/'documentation-ledger.json').read_text())['sources'];source_records=[]
 for service,url in SPECS.items():
  record=next(x for x in ledger if x['url']==url and x.get('http_status')==200);raw=(BASE/record['file']).read_text();spec=yaml.safe_load(raw)
  if not isinstance(spec,dict) or 'openapi' not in spec:raise ValueError('documented_openapi_required')
  base=spec['servers'][0]['url'].rstrip('/');methods=catalogue['services'][service]['methods']
  for path,entries in spec['paths'].items():
   for verb,op in entries.items():
    if verb not in {'get','post','patch','put','delete'}:continue
    operation=op.get('operationId') or verb+'_'+path
    key='api_'+re.sub('[^A-Za-z0-9_]+','_',operation).strip('_')
    if len(key)>125:key=key[:100]+'_'+sha(key)[:16]
    if key in methods:raise ValueError('duplicate_documented_operation_id')
    properties={};required=[];locations={};unsupported=[]
    for param in entries.get('parameters',[])+op.get('parameters',[]):
     param=local_ref(spec,param);location=param['in'];name=param['name']
     if location not in {'path','query','header'}:unsupported.append('parameter_location:'+location);continue
     if location=='header' and name.lower() in {'authorization','x-api-key','cookie','host','content-type'}:continue
     section=properties.setdefault(location,{'type':'object','properties':{},'additionalProperties':False});section['properties'][name]=convert_nullable(param.get('schema',{}))
     locations.setdefault(location,[]).append({'name':name,'style':param.get('style'),'explode':param.get('explode',True)})
     if param.get('required'):section.setdefault('required',[]).append(name)
    if op.get('requestBody'):
     body=local_ref(spec,op['requestBody']);content=body.get('content',{})
     if 'application/json' in content:properties['body']=convert_nullable(content['application/json'].get('schema',{}))
     else:unsupported.append('request_content:'+','.join(content))
     if body.get('required'):required.append('body')
    for section in ['path','query','header']:
     if properties.get(section,{}).get('required'):required.append(section)
    schema={'type':'object','properties':properties,'required':required,'additionalProperties':False}
    try:schema=close_references(schema,convert_nullable(spec))
    except (KeyError,ValueError):unsupported.append('schema_dependency_requires_additional_pinned_source')
    category=effect(service,verb,path)
    if unsupported:category='blocked'
    methods[key]={'description':op.get('summary',op.get('description',''))+'; '+verb.upper()+' '+path,'input_schema':schema,'schema_sha256':sha(canonical(schema)),'effect':category,'api_request':{'method':verb.upper(),'base':base,'path':path,'parameters':locations},'source_url':url,'source_sha256':record['sha256'],'openapi_version':spec['openapi'],'unsupported':unsupported,'semantic_test':'not_run'}
  source_records.append({'service':service,'url':url,'source_sha256':record['sha256'],'paths':len(spec['paths']),'read_entire_spec':True,'algorithm':'JSON/YAML parsed in full, every path/operation/parameter/body schema included; not all operations executed.'})
 return source_records
