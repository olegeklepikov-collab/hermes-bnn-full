"""Build local blueprints from the five downloaded official OpenAPI files."""
import copy, json, hashlib
from pathlib import Path
P = Path(__file__).resolve().parent
PRODUCTS = {
 'starter': ('wos-starter', 'https://api.clarivate.com/apis/wos-starter/v2'),
 'expanded': ('wos', 'https://api.clarivate.com/api/wos'),
 'researcher': ('wos-researcher', 'https://api.clarivate.com/apis/wos-researcher'),
 'journals': ('wos-journal', 'https://api.clarivate.com/apis/wos-journals/v1'),
 'incites': ('incites', 'https://incites-api.clarivate.com/api/incites'),
}
NAMES = {
 'starter': {('/documents','get'):'search',('/documents/{uid}','get'):'document',('/journals','get'):'journals',('/journals/{id}','get'):'journal'},
 'expanded': {('/','get'):'search',('/','post'):'search_post',('/id/{uniqueId}','get'):'document',('/query/{queryId}','get'):'query_page',('/recordids/{queryId}','get'):'record_ids',('/related','get'):'related',('/citing','get'):'citing',('/references','get'):'references',('/category-context/{uniqueId}','get'):'category_context',('/citation-report/{queryId}','get'):'citation_report'},
 'researcher': {('/researchers','get'):'search',('/researchers/{rid}','get'):'profile',('/researchers/{rid}/peer-reviews','get'):'peer_reviews',('/researchers/{rid}/documents','get'):'documents'},
 'journals': {('/journals','get'):'search',('/journals/{id}','get'):'journal',('/journals/{id}/reports/year/{year}','get'):'year_report',('/journals/{id}/cited/year/{year}','get'):'cited',('/journals/{id}/citing/year/{year}','get'):'citing',('/journals/{id}/history','get'):'history',('/categories','get'):'categories',('/categories/{id}','get'):'category',('/categories/{id}/reports/year/{year}','get'):'category_year_report',('/categories/{id}/cited/year/{year}','get'):'category_cited',('/categories/{id}/citing/year/{year}','get'):'category_citing',('/last-updated','get'):'last_updated',('/journals/history/title','get'):'title_changes'},
 'incites': {('/DocumentLevelMetricsByInstitutionId/json','get'):'institution_metrics',('/DocumentLevelMetricsByInstitutionIdRecordCount/json','get'):'institution_count',('/DocumentLevelMetricsByUT/json','get'):'document_metrics',('/CheckValidUTs/json','get'):'validate_uids',('/InCitesLastUpdated/json','get'):'last_updated'},
}
def clean(s):
 s = copy.deepcopy(s)
 for k in ['example','format','nullable']:s.pop(k,None)
 if 'default' in s:
  if s.get('type')=='string' and not isinstance(s['default'],str):s['default']=str(s['default'])
 if s.get('type')=='integer':
  s['minimum']=max(s.get('minimum',0),0)
 if s.get('type')=='string':s['maxLength']=8000
 return s
operations={}; provenance=[]
for product,(file,base) in PRODUCTS.items():
 raw=(P/'источники'/f'{file}-openapi.json').read_bytes(); spec=json.loads(raw)
 assert base in [x['url'] for x in spec['servers']]
 provenance.append({'product':product,'url':'https://developer.clarivate.com/apis/'+file+'/swagger','sha256':hashlib.sha256(raw).hexdigest(),'downloaded_at':'2026-10-07','version':spec['info']['version']})
 for (path,method),name in NAMES[product].items():
  op=spec['paths'][path][method];properties={};required=[];fields={'path':[],'query':[],'body':[]};defaults={}
  for arg in op.get('parameters',[]):
   if arg['in']=='header':continue
   key=arg['name'];s=clean(arg['schema']);s['description']=arg.get('description','')[:1000]
   if key in ['limit','count','recordcount']:
    s['minimum']=0 if key=='count' else 1;s['maximum']=100 if product in ['expanded','incites'] else 50
   if key in ['page','firstRecord','startingrecord','queryId']:s['minimum']=1
   properties[key]=s;fields[arg['in']].append(key)
   if arg.get('required'):required.append(key)
   if 'default' in s:defaults[key]=s['default']
  body=op.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
  if body:
   for key,value in body['properties'].items():
    s=clean(value)
    if key=='count':s.update(minimum=0,maximum=100)
    if key=='firstRecord':s['minimum']=1
    s['description']=s.get('description','')[:1000];properties[key]=s;fields['body'].append(key)
    if 'default' in s:defaults[key]=s['default']
   required+=body['required']
  if product=='expanded' and 'databaseId' in properties:defaults['databaseId']='WOS'
  if product=='expanded' and 'optionView' in properties:defaults['optionView']='SR'
  if 'count' in properties:defaults['count']=3
  if 'limit' in properties:defaults['limit']=3
  if 'firstRecord' in properties:defaults['firstRecord']=1
  properties['purpose']={'type':'string','enum':['academic','business','general'],'default':'academic','description':'Назначение должно быть разрешено письменным соглашением.'}
  operations[product+'_'+name]={'product':product,'method':method.upper(),'base_url':base,'path':path,'fields':fields,'defaults':defaults,
      'description':(op.get('summary') or name.replace('_',' '))[:220]+'. Требуются отдельное разрешение на ИИ и ключ; полные метаданные не равны тексту статьи.',
      'input_schema':{'type':'object','properties':properties,'required':list(dict.fromkeys(required)),'additionalProperties':False}}
profiles={
 'academic-discovery':{'name':'starter_search','arguments':{'db':'WOS','limit':3},'template':{'q':'TS=({topic})'}},
 'business-discovery':{'name':'starter_search','arguments':{'db':'WOS','limit':3,'purpose':'business'},'template':{'q':'TS=({topic})'}},
 'general-discovery':{'name':'starter_search','arguments':{'db':'WOS','limit':3,'purpose':'general'},'template':{'q':'TS=({topic})'}},
 'doi-lookup':{'name':'starter_search','arguments':{'db':'WOS','limit':2},'template':{'q':'DO=({doi})'}},
 'exact-title':{'name':'starter_search','arguments':{'db':'WOS','limit':3},'template':{'q':'TI=("{title}")'}},
 'author-discovery':{'name':'starter_search','arguments':{'db':'WOS','limit':3},'template':{'q':'AU=({author})'}},
 'publication-period':{'name':'starter_search','arguments':{'db':'WOS','limit':3},'template':{'q':'TS=({topic}) AND PY=({year_from}-{year_to})'}},
 'reviews':{'name':'starter_search','arguments':{'db':'WOS','limit':3},'template':{'q':'TS=({topic}) AND DT=(Review)'}},
 'expanded-abstracts-and-funding':{'name':'expanded_search','arguments':{'databaseId':'WOS','count':3,'firstRecord':1,'optionView':'FR'},'template':{'usrQuery':'TS=({topic})'}},
 'expanded-short-discovery':{'name':'expanded_search','arguments':{'databaseId':'WOS','count':3,'firstRecord':1,'optionView':'SR'},'template':{'usrQuery':'TS=({topic})'}},
 'expanded-reproducible-query':{'name':'expanded_search_post','arguments':{'databaseId':'WOS','count':3,'firstRecord':1,'optionView':'SR'}},
 'expanded-publication-period':{'name':'expanded_search','arguments':{'databaseId':'WOS','count':3,'firstRecord':1,'optionView':'SR'},'template':{'usrQuery':'TS=({topic}) AND PY=({year_from}-{year_to})'}},
}
for name,op in operations.items():
 profiles.setdefault(name.replace('_','-'),{'name':name,'arguments':op['defaults']})
profiles.update({'researcher-affiliation':{'name':'researcher_search','arguments':{'limit':3},'template':{'q':'OG~"{organization}"'}},
 'journals-quartile':{'name':'journals_search','arguments':{'jifQuartile':'Q1','limit':3}},
 'journals-explicit-year':{'name':'journals_year_report','arguments':{}},
 'incites-normalized-impact':{'name':'incites_document_metrics','arguments':{'ver':2,'schema':'wos','esci':'y'}}})
for filename,obj in [('operations.json',operations),('profiles.json',profiles),('spec-provenance.json',provenance)]:
 p=P/'config'/filename;p.write_text(json.dumps(obj,ensure_ascii=False,indent=2));p.chmod(0o600)
products={name:{'documentation':'https://developer.clarivate.com/apis/'+file,'base_url':base,'key_name':'WOS_BN_'+name.upper()+'_API_KEY','enabled':False,'configured_plan':'free_trial' if name=='starter' else 'not_subscribed','request_interval_seconds':1.1,'daily_request_cap':50,'records_per_request_cap':3,'live_verified':False} for name,(file,base) in PRODUCTS.items()}
for filename,obj in [('products.json',products),('access-approval.json',{'ai_use_authorized':False,'written_permission_document':None,'permission_reference':None,'allowed_products':[],'allowed_purposes':[],'expires_on':None,'reviewed_by_owner':False,'llm_service':'ChatGPT','terms_reference':'https://clarivate.com/wp-content/uploads/dlm_uploads/2025/05/Product-Terms-Web-of-Science-APIs-v3.8.pdf','reason':'section 4(a): AI Addendum or other written agreement required'}),('verification.json',{'mock_transport_only':True,'live_api_checked':False,'cli_checked':False,'native_backend_checked':False,'telegram_checked':False})]:
 p=P/'config'/filename
 if not p.exists():p.write_text(json.dumps(obj,ensure_ascii=False,indent=2));p.chmod(0o600)
print('API operations',len(operations),'profiles',len(profiles),'data access disabled')
