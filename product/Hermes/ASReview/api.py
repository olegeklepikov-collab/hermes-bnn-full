"""Local ASReview 3 bridge for Hermes BN. No remote review data or arbitrary code."""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
from dataclasses import asdict
import contextlib,copy,hashlib,importlib.metadata,io,json,os,re,sys,time,uuid,zipfile,shutil
import numpy as np,pandas as pd
import asreview as asr
from asreview.models import get_ai_config
from filelock import FileLock
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parent; R=ROOT.parent
OPS={}
S={'type':'string','minLength':1}; I={'type':'integer','minimum':0}; B={'type':'boolean'}
def enum(*v):return {'type':'string','enum':list(v)}
def integer(lo=0,hi=100000):return {'type':'integer','minimum':lo,'maximum':hi}
def arr(v,maxn=100):return {'type':'array','items':v,'maxItems':maxn}
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
def op(name,description,properties={},required=()):
 def decorate(fn):
  OPS[name]={'description':description,'input_schema':obj(properties,required),'fn':fn};return fn
 return decorate
def now():return datetime.now(timezone.utc).isoformat()
def clean(v):
 if isinstance(v,pd.DataFrame):return json.loads(v.to_json(orient='records',force_ascii=False))
 if isinstance(v,np.ndarray):return v.tolist()
 if isinstance(v,np.generic):return v.item()
 if isinstance(v,Path):return str(v)
 if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [clean(x) for x in v]
 return v
def dump(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(clean(d),ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,p)
def slug(x):
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',x):raise ValueError('Use a project identifier with 1–80 letters, digits, hyphens or underscores')
 return x
def path(x):
 p=Path(x).expanduser().resolve()
 if not p.is_relative_to(R):raise ValueError('Input must be a local file inside Hermes BN on AgentRuntime2')
 if not p.is_file() or p.stat().st_size>50_000_000:raise ValueError('Input file missing or over 50 MB')
 return p
def output(name,suffix):
 p=ROOT/'exports'/(slug(name)+'-'+uuid.uuid4().hex[:8]+suffix);return p
@contextlib.contextmanager
def project(project_id):
 p=ROOT/'projects'/slug(project_id)
 if not asr.is_project(p):raise ValueError('ASReview project not found')
 with asr.Project(p) as q:yield q
def event(p,action,data):
 fp=p.project_path/'hermes-audit.jsonl'
 with fp.open('a') as f:f.write(json.dumps({'at':now(),'action':action,**clean(data)},ensure_ascii=False)+'\n')
 fp.chmod(0o600)
def frame(fp):
 p=path(fp)
 if p.suffix.lower()=='.json':
  d=json.loads(p.read_text());
  if isinstance(d,dict):
   for key in ['records','results','items']:
    if isinstance(d.get(key),list):d=d[key];break
  if not isinstance(d,list):raise ValueError('JSON must contain normalized record rows in a list or records/results/items')
  df=pd.DataFrame(d)
 else:
  from asreview.data import CSVReader,ExcelReader,RISReader
  reader=RISReader if p.suffix.lower() in ['.ris','.txt'] else ExcelReader if p.suffix.lower()=='.xlsx' else CSVReader
  df=reader.clean_data(reader.read_data(str(p)))
 if len(df)>100000:raise ValueError('At most 100000 records per dataset')
 if not ({'title','abstract'}&set(df)):raise ValueError('At least title or abstract is required')
 for c in ['title','abstract']:
  if c not in df:df[c]=''
  df[c]=df[c].fillna('').astype(str)
 if ((df.title.str.strip()=='')&(df.abstract.str.strip()=='')).any():raise ValueError('Rows without both title and abstract must be corrected')
 if 'included' in df:
  df['included']=pd.to_numeric(df.included,errors='raise').astype('Int64')
  if not df.included.dropna().isin([0,1]).all():raise ValueError('Labels must be 0, 1 or empty; empty does not mean excluded')
 return df
def summary(df):
 labels=df['included'] if 'included'in df else pd.Series([None]*len(df))
 titles=df.title.fillna('').str.casefold().str.replace(r'\s+',' ',regex=True).str.strip()
 return {'records':len(df),'columns':list(df),'missing_titles':int((df.title.str.strip()=='').sum()),'missing_abstracts':int((df.abstract.str.strip()=='').sum()),'labels':{'relevant':int((labels==1).sum()),'irrelevant':int((labels==0).sum()),'unseen':int(labels.isna().sum())},'repeated_nonempty_titles':int(titles[titles!=''].duplicated().sum()),'reading_level':'Only imported title/abstract/metadata; no source papers read'}
def dataset(p):return p.db.input.get_df().sort_values('record_id').reset_index(drop=True)
def results(p):return p.db.get_results_table(groups=True)
def unique_results(p):return p.db.get_results_table(groups=False)
def settings():return json.loads((ROOT/'config/models.json').read_text())
def model_meta(name,seed=42):
 models=settings()
 if name not in models:raise ValueError('Model not in selected registry')
 meta=copy.deepcopy(models[name]['value'])
 for group in ['querier','classifier']:
  if meta.get(group):
   cls=asr.load_extension('models.'+('queriers' if group=='querier' else 'classifiers'),meta[group])
   if 'random_state' in __import__('inspect').signature(cls).parameters:meta.setdefault(group+'_param',{})['random_state']=seed
 return meta
def configure(p,name,seed):
 meta=model_meta(name,seed);p.update_review(model=meta,model_name=name);dump(p.project_path/'hermes-model.json',{'name':name,'seed':seed,'value':meta,'configured_at':now()});return meta
def ranked(p):
 df=dataset(p);labelled=set(results(p).record_id.astype(int));unseen=df[~df.record_id.isin(labelled)&(df.record_id==df.group_id)]
 ranking=p.db.get_last_ranking_table();order={int(v):i for i,v in enumerate(ranking.record_id)}
 return unseen.assign(priority=unseen.record_id.map(order).fillna(len(df)+unseen.record_id)).sort_values('priority')
def stats(p):
 df=dataset(p);rr=results(p);ur=unique_results(p);labels=rr.label
 unseen=df[~df.record_id.isin(rr.record_id)]
 rank=p.db.get_last_ranking_table();train=int(rank.training_set.iloc[0]) if len(rank) and not pd.isna(rank.training_set.iloc[0]) else None
 trailing=0
 for x in reversed(ur.label.tolist()):
  if x!=0:break
  trailing+=1
 return {'project_id':p.project_id,'mode':p.config['mode'],'workflow':json.loads((p.project_path/'hermes-workflow.json').read_text())['mode'] if (p.project_path/'hermes-workflow.json').exists() else p.config['mode'],'records':len(df),'unique_groups':int(df.group_id.nunique()),'duplicate_records':int((df.record_id!=df.group_id).sum()),'labelled_records':len(rr),'labelled_groups':len(ur),'relevant_records':int((labels==1).sum()),'irrelevant_records':int((labels==0).sum()),'unseen_records':len(unseen),'unseen_groups':int(unseen.group_id.nunique()),'consecutive_irrelevant_groups':trailing,'ranking_training_records':train,'ranking_may_be_stale':train is None or train!=len(rr),'recall_of_real_review':None,'limitation':'Unknown relevance among unseen records; ranking and consecutive exclusions do not establish exhaustive retrieval or recall.'}
@op('service_status','Проверить местную установку ASReview, модели, каталоги и состояние LAB.')
def service_status():
 import urllib.request
 try:
  with urllib.request.urlopen('http://127.0.0.1:60694/',timeout=2) as resp:lab=resp.status
 except Exception:lab=None
 weights=json.loads((ROOT/'config/model-snapshots.json').read_text())
 weight_status={repo:{'revision':d['revision'],'safetensors_present':(Path(d['path'])/'model.safetensors').is_file(),'path_on_AgentRuntime2':Path(d['path']).resolve().is_relative_to(ROOT),'license':d.get('license')} for repo,d in weights.items()}
 return {'version':asr.__version__,'python':sys.version.split()[0],'packages':{n:importlib.metadata.version(n) for n in ['asreview-dory','scikit-learn','sentence-transformers','torch']},'root':str(ROOT),'lab_url':'http://127.0.0.1:60694/','lab_http_status':lab,'api_key_required':False,'models':list(settings()),'model_weights':weight_status,'method_count':len(OPS),'data_transmission':'ASReview inference is local. Text returned to Hermes is processed by its configured model provider.'}
@op('model_catalog','Получить выбранные модели и их точные параметры; составные модели ASReview доступны отдельно.')
def model_catalog():return {'models':settings(),'components':{g:[e.name for e in importlib.metadata.entry_points(group='asreview.models.'+g)] for g in ['classifiers','feature_extractors','queriers','balancers','stoppers']}}
@op('inspect_dataset','Проверить местный CSV/RIS/XLSX/TSV/JSON: поля, пропуски, метки и повторы названий.',{'file':S},['file'])
def inspect_dataset(file):return {**summary(frame(file)),'file':str(path(file)),'sha256':hashlib.sha256(path(file).read_bytes()).hexdigest()}
@op('prepare_dataset','Создать нормализованную копию данных CSV; исходный файл сохраняется. Не превращает пропуски в исключения.',{'file':S,'name':S},['file','name'])
def prepare_dataset(file,name):
 df=frame(file);out=output(name,'.csv');df.to_csv(out,index=False);dump(out.with_suffix('.source.json'),{'source':str(path(file)),'source_sha256':hashlib.sha256(path(file).read_bytes()).hexdigest(),'at':now(),'columns':list(df),'row_count':len(df)});return {'file':str(out),**summary(df)}
@op('create_project','Создать отдельный местный обзор или проверку ранее заданных меток; требуется протокол критериев перед реальными решениями.',{'project_id':S,'file':S,'mode':enum('oracle','validate'),'model':S,'seed':integer(0,2147483647)},['project_id','file'])
def create_project(project_id,file,mode='oracle',model='elas_u4',seed=42):
 df=frame(file);model_meta(model,seed);fp=path(file);original_fp=fp
 if fp.suffix.lower()=='.json':fp=Path(prepare_dataset(file,project_id)['file'])
 with asr.Project.create(ROOT/'projects'/slug(project_id),project_id=project_id,project_mode='oracle',project_name=project_id) as p:
  p.add_dataset(str(fp),dataset_id=fp.name)
  original_dir=p.project_path/'source-original';original_dir.mkdir(exist_ok=True);shutil.copy2(path(file),original_dir/path(file).name)
  configure(p,model,seed)
  dump(p.project_path/'hermes-workflow.json',{'mode':mode,'underlying_asreview_mode':'oracle','input_labels_used_as_priors':mode=='oracle'})
  if mode=='oracle':
   # ASReview 3.0.8 label_priors skips fully labelled sets; explicit copy here honours owner-supplied labels.
   for row in dataset(p).itertuples():
    if not pd.isna(row.included):p.db.label_record(int(row.record_id),int(row.included))
  p.update_review(status='review');event(p,'create',{'source':str(fp),'source_sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),'seed':seed,'imported_labels_used_as_priors':mode=='oracle'})
  return stats(p)
@op('list_projects','Перечислить местные проекты ASReview без чтения статей.')
def list_projects():return {'projects':[{'project_id':p.name,'name':json.loads((p/'project.json').read_text()).get('name')} for p in sorted((ROOT/'projects').iterdir()) if asr.is_project(p)]}
@op('project_info','Получить параметры проекта, происхождение данных, модель и ход отбора.',{'project_id':S},['project_id'])
def project_info(project_id):
 with project(project_id) as p:return {'config':p.config,'progress':stats(p),'protocol_present':(p.project_path/'hermes-protocol.json').exists()}
@op('list_records','Прочитать ограниченную страницу импортированных названий и аннотаций с метками.',{'project_id':S,'offset':I,'limit':integer(1,100),'filter':enum('all','unseen','relevant','irrelevant')},['project_id'])
def list_records(project_id,offset=0,limit=20,filter='all'):
 with project(project_id) as p:
  df=dataset(p).merge(results(p)[['record_id','label']],on='record_id',how='left')
  if filter=='unseen':df=df[df.label.isna()]
  if filter in ['relevant','irrelevant']:df=df[df.label==(1 if filter=='relevant' else 0)]
  return {'total':len(df),'offset':offset,'records':clean(df.iloc[offset:offset+limit]),'reading_level':'Only returned imported title/abstract/metadata'}
@op('get_record','Прочитать одну импортированную запись, историю решения и заметку; полный текст не загружается.',{'project_id':S,'record_id':I},['project_id','record_id'])
def get_record(project_id,record_id):
 with project(project_id) as p:
  df=dataset(p);row=df[df.record_id==record_id]
  if row.empty:raise ValueError('Record not found')
  rr=results(p);return {'record':clean(row)[0],'decision':clean(rr[rr.record_id==record_id]),'reading_level':'Imported title/abstract/metadata only'}
PROTOCOL=obj({'question':S,'include':arr(S),'exclude':arr(S),'stage':enum('title_abstract','full_text','documents'),'stop_rule':S,'reviewer_policy':S},['question','include','exclude','stage','stop_rule','reviewer_policy'])
@op('set_protocol','Сохранить вопрос, критерии включения/исключения, этап и правила проверки и остановки. Не меняет научных решений.',{'project_id':S,'protocol':PROTOCOL},['project_id','protocol'])
def set_protocol(project_id,protocol):
 with project(project_id) as p:dump(p.project_path/'hermes-protocol.json',{'at':now(),**protocol});event(p,'protocol',{'protocol':protocol});return {'protocol':protocol}
@op('get_protocol','Прочитать сохранённый протокол отбора.',{'project_id':S},['project_id'])
def get_protocol(project_id):
 with project(project_id) as p:
  f=p.project_path/'hermes-protocol.json';return {'protocol':json.loads(f.read_text()) if f.exists() else None}
@op('configure_model','Выбрать подготовленную модель и начальное состояние генератора; прежние решения сохраняются.',{'project_id':S,'model':S,'seed':integer(0,2147483647)},['project_id','model'])
def configure_model(project_id,model,seed=42):
 with project(project_id) as p:meta=configure(p,model,seed);event(p,'configure_model',{'model':model,'seed':seed});return {'model':model,'seed':seed,'value':meta,'requires_reranking':True}
@op('train_rank','Обучить модель по существующим двум классам и обновить приоритеты. Вероятности не означают научную достоверность.',{'project_id':S},['project_id'])
def train_rank(project_id):
 with project(project_id) as p:
  df=dataset(p);rr=results(p);meta=p.get_model_config()
  if meta.get('classifier') and set(rr.label.dropna().astype(int))!={0,1}:raise ValueError('At least one relevant and one irrelevant confirmed record required')
  heavy=meta.get('feature_extractor') in ['multilingual-e5-large','mxbai']
  if len(df)>(5000 if heavy else 30000):raise ValueError('Local limit: 5000 dense-model records or 30000 sparse-model records; split or plan a larger run')
  signature=hashlib.sha256(df[['record_id','title','abstract']].to_json().encode()).hexdigest()
  key='bn-'+hashlib.sha256(json.dumps({'feature':meta.get('feature_extractor'),'params':meta.get('feature_extractor_param'),'data':signature},sort_keys=True).encode()).hexdigest()[:20]
  cycle=asr.ActiveLearningCycle.from_meta(asr.ActiveLearningCycleData(**meta))
  cache=False
  if cycle.feature_extractor:
   try:fm=p.get_feature_matrix(key);cache=True
   except ValueError:fm=cycle.transform(df);p.add_feature_matrix(fm,key)
  else:fm=df.values
  if cycle.classifier is not None:
   index={int(v):i for i,v in enumerate(df.record_id)};positions=[index[int(v)] for v in rr.record_id]
   cycle.fit(fm[positions],rr.label.astype(int).to_numpy())
  ranked_ids=df.record_id.to_numpy()[cycle.rank(fm)]
  p.db.add_last_ranking(np.asarray(ranked_ids,dtype=np.int64),meta.get('classifier'),meta['querier'],meta.get('balancer'),meta.get('feature_extractor'),len(rr))
  event(p,'train_rank',{'model':p.config['review']['model'].get('name'),'training_records':len(rr),'matrix_key':key,'cached_features':cache})
  return {'ranked':len(ranked_ids),'training_records':len(rr),'feature_cache_used':cache,'progress':stats(p),'meaning':'Priority for screening, not an inclusion decision or calibrated probability'}
@op('next_records','Получить очередные неразмеченные уникальные записи по последнему ранжированию; решения не записываются.',{'project_id':S,'limit':integer(1,100)},['project_id'])
def next_records(project_id,limit=5):
 with project(project_id) as p:return {'records':clean(ranked(p).head(limit)),'progress':stats(p),'reading_level':'Only returned imported title/abstract/metadata'}
DECISION=obj({'record_id':I,'label':enum('relevant','irrelevant'),'reason':S},['record_id','label','reason'])
@op('propose_decisions','Сохранить предложения агента отдельно от подтверждённых меток; обучение по предложениям не запускается.',{'project_id':S,'decisions':arr(DECISION,100),'basis':S},['project_id','decisions','basis'])
def propose_decisions(project_id,decisions,basis):
 with project(project_id) as p:
  ids=set(dataset(p).record_id.astype(int))
  if any(d['record_id'] not in ids for d in decisions):raise ValueError('Unknown record in proposals')
  event(p,'agent_proposals',{'decisions':decisions,'basis':basis,'status':'unconfirmed_not_used_for_training'})
  return {'proposed':len(decisions),'confirmed_labels_changed':0}
@op('record_decision','Записать или исправить явно заданное человеком решение либо синтетическую проверку; сохраняются причина, этап и история. Совпадающие записи получают общее решение ASReview.',{'project_id':S,'record_id':I,'label':enum('relevant','irrelevant'),'reason':S,'actor':enum('human','synthetic_test'),'tags':arr(S,30)},['project_id','record_id','label','reason','actor'])
def record_decision(project_id,record_id,label,reason,actor,tags=None):
 with project(project_id) as p:
  if actor=='synthetic_test' and not (p.project_path/'synthetic.json').exists():raise ValueError('Synthetic labels allowed only in a marked synthetic project')
  if not (p.project_path/'hermes-protocol.json').exists():raise ValueError('Set screening protocol before confirming decisions')
  df=dataset(p);row=df[df.record_id==record_id]
  if row.empty:raise ValueError('Record not found')
  group=int(row.group_id.iloc[0]);affected=df[df.group_id==group].record_id.astype(int).tolist()
  p.db.label_record(record_id,1 if label=='relevant' else 0,tags=tags)
  p.db.update_note(record_id,json.dumps({'reason':reason,'actor':actor,'stage':get_protocol(project_id)['protocol']['stage']},ensure_ascii=False))
  event(p,'decision',{'record_id':record_id,'affected_group_records':affected,'label':label,'reason':reason,'actor':actor,'tags':tags});return {'affected_record_ids':affected,'progress':stats(p)}
@op('progress','Получить количества исходных/уникальных/размеченных записей и ограничения оценки полноты.',{'project_id':S},['project_id'])
def progress(project_id):
 with project(project_id) as p:return stats(p)
@op('decision_history','Прочитать изменения решений ASReview и журнал действий Hermes.',{'project_id':S,'limit':integer(1,100)},['project_id'])
def decision_history(project_id,limit=30):
 with project(project_id) as p:
  audit=p.project_path/'hermes-audit.jsonl'
  return {'changes':clean(p.db.get_decision_changes().tail(limit)),'hermes_events':[json.loads(l) for l in audit.read_text().splitlines()[-limit:]] if audit.exists() else []}
@op('sample_audit','Получить воспроизводимую случайную выборку ещё не просмотренных уникальных записей; ничего не исключать.',{'project_id':S,'size':integer(1,100),'seed':integer(0,2147483647)},['project_id'])
def sample_audit(project_id,size=20,seed=42):
 with project(project_id) as p:
  df=ranked(p);return {'seed':seed,'population_unseen_groups':len(df),'records':clean(df.sample(n=min(size,len(df)),random_state=seed)),'limitation':'A sample alone does not guarantee recall; use a predeclared audit and stopping protocol'}
@op('export_dataset','Сохранить отбор в CSV/TSV/XLSX/JSON/RIS и отдельные исходные поля с историей; нерешённые записи остаются пустыми.',{'project_id':S,'format':enum('csv','tsv','xlsx','json','ris'),'filter':enum('all','relevant','irrelevant','unseen'),'include_duplicates':B},['project_id','format'])
def export_dataset(project_id,format,filter='all',include_duplicates=True):
 with project(project_id) as p:
  df=dataset(p);rr=results(p);df=df.merge(rr[['record_id','label','note','time']],on='record_id',how='left');df=df.rename(columns={'included':'input_label','label':'included','note':'asreview_note','time':'asreview_time'})
  if not include_duplicates:df=df[df.record_id==df.group_id]
  if filter=='unseen':df=df[df.included.isna()]
  if filter in ['relevant','irrelevant']:df=df[df.included==(1 if filter=='relevant' else 0)]
  out=output(project_id,'.'+format);original=clean(df);safe=df.drop(columns=['dataset_id','dataset_row','duplicate_of','group_id'],errors='ignore').copy()
  for c in safe.select_dtypes(include='object').columns:
   safe[c]=safe[c].map(lambda v:"'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v)
  if format=='json':dump(out,original)
  elif format in ['csv','tsv']:safe.to_csv(out,index=False,sep='\t' if format=='tsv' else ',')
  elif format=='xlsx':safe.to_excel(out,index=False)
  else:
   import rispy
   ris=[]
   for row in original:
    rec={'type_of_reference':'JOUR','primary_title':row.get('title'),'abstract':row.get('abstract'),'authors':row.get('authors') or [],'year':str(row['year']) if row.get('year') else None,'doi':row.get('doi'),'url':row.get('url'),'notes':[('ASReview_relevant' if row.get('included')==1 else 'ASReview_irrelevant' if row.get('included')==0 else 'ASReview_not_seen'), 'Hermes BN source record_id: '+str(row['record_id'])]}
    if row.get('asreview_note'):rec['notes'].append(row['asreview_note'])
    ris.append({k:v for k,v in rec.items() if v is not None})
   with out.open('w') as f:rispy.dump(ris,f)
  dump(out.with_suffix(out.suffix+'.source.json'),{'at':now(),'project':p.project_id,'format':format,'records':original,'duplicate_records_included':include_duplicates,'ris_note':'RIS conversion may omit unsupported fields; ASReview record fields retained here; preserve the original input file stored in the project for additional source fields','protocol':get_protocol(project_id)['protocol']})
  return {'file':str(out),'source_and_decisions':str(out.with_suffix(out.suffix+'.source.json')),'record_count':len(df),'filter':filter}
@op('export_project','Сохранить переносимую копию проекта .asreview с настройками, данными и решениями.',{'project_id':S},['project_id'])
def export_project(project_id):
 with project(project_id) as p:
  out=output(project_id,'.asreview');p.export(out);return {'file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'project_id':p.project_id}
@op('import_project','Импортировать копию архива .asreview под новым идентификатором; исходный проект сохраняется, исполняемые файлы не принимаются.',{'file':S,'project_id':S},['file','project_id'])
def import_project(file,project_id):
 fp=path(file);target=ROOT/'projects'/slug(project_id)
 if target.exists():raise ValueError('Target exists; choose a new project id')
 with zipfile.ZipFile(fp) as archive:
  infos=archive.infolist()
  if sum(i.file_size for i in infos)>500_000_000:raise ValueError('Unpacked project exceeds 500 MB')
  for i in infos:
   q=PurePosixPath(i.filename)
   if q.is_absolute() or '..' in q.parts or '\\' in i.filename or (i.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive member')
   if q.suffix.lower() in ['.pickle','.pkl','.py','.so','.dylib','.sh']:raise ValueError('Executable model/archive content is not accepted')
  if 'project.json' not in archive.namelist():raise ValueError('Missing project.json')
  cfg=json.loads(archive.read('project.json'))
  if cfg.get('project_file_version')!=asr.Project.VERSION:raise ValueError('Only current ASReview project format is enabled; migrate a separate copy of older projects with the official library first')
  for fm in cfg.get('feature_matrices',[]):
   name=fm.get('filename','');q=PurePosixPath(name)
   if not name or q.is_absolute() or '..' in q.parts or len(q.parts)!=1 or q.suffix not in ['.npy','.npz']:raise ValueError('Unsafe feature matrix reference')
  for d in cfg.get('datasets',[]):
   q=PurePosixPath(d.get('name',''))
   if q.is_absolute() or '..' in q.parts or len(q.parts)!=1:raise ValueError('Unsafe dataset reference')
  archive.extractall(target)
 cfg=json.loads((target/'project.json').read_text());cfg['id']=project_id;dump(target/'project.json',cfg)
 with project(project_id) as p:event(p,'import_project',{'source':str(fp),'source_sha256':hashlib.sha256(fp.read_bytes()).hexdigest()});return stats(p)
@op('simulate','Смоделировать отбор на полностью размеченных данных с заданными моделью, начальными примерами и ограничением просмотра.',{'project_id':S,'file':S,'model':S,'seed':integer(0,2147483647),'stop':enum('all','last_relevant','n_labelled','consecutive_irrelevant'),'stop_value':integer(1,100000)},['project_id','file'])
def simulate(project_id,file,model='elas_u4',seed=42,stop='all',stop_value=100):
 df=frame(file)
 if 'included' not in df or df.included.isna().any() or set(df.included.astype(int))!={0,1}:raise ValueError('Simulation requires complete ground-truth labels with both classes')
 if len(df)>5000:raise ValueError('Interactive simulation limit: 5000 records')
 from asreview.models.queriers import TopDown
 from asreview.models.stoppers import IsFittable,LastRelevant,NLabeled,NConsecutiveIrrelevant
 meta=model_meta(model,seed);cycle=asr.ActiveLearningCycle.from_meta(asr.ActiveLearningCycleData(**meta));stopper={'all':NLabeled(len(df)),'last_relevant':LastRelevant(),'n_labelled':NLabeled(stop_value),'consecutive_irrelevant':NConsecutiveIrrelevant(stop_value)}[stop]
 fp=path(file)
 if fp.suffix.lower()=='.json':fp=Path(prepare_dataset(file,project_id)['file'])
 with asr.Project.create(ROOT/'projects'/slug(project_id),project_id=project_id,project_mode='simulate') as p:
  p.add_dataset(str(fp),dataset_id=fp.name);configure(p,model,seed)
  original_dir=p.project_path/'source-original';original_dir.mkdir(exist_ok=True);shutil.copy2(path(file),original_dir/path(file).name)
  d=dataset(p);rng=np.random.RandomState(seed);prior=[int(rng.choice(d[d.included==v].record_id)) for v in [1,0]]
  sim=asr.Simulate(d,d.included,[asr.ActiveLearningCycle(TopDown(),stopper=IsFittable()),cycle],stopper=stopper,groups=p.db.input.get_groups(),print_progress=False)
  sim.label(prior);sim.review();sim.to_sql(p.db_path);p.update_review(status='finished')
  dump(p.project_path/'hermes-simulation.json',{'model':model,'seed':seed,'priors':prior,'stop':stop,'stop_value':stop_value,'source':str(fp),'source_sha256':hashlib.sha256(fp.read_bytes()).hexdigest()});event(p,'simulation',{'seed':seed,'priors':prior,'stop':stop});return simulation_report(project_id)
@op('simulation_report','Рассчитать фактически найденную долю релевантных записей и затраты просмотра только для полностью размеченного моделирования.',{'project_id':S},['project_id'])
def simulation_report(project_id):
 with project(project_id) as p:
  if p.config['mode']!='simulate':raise ValueError('Recall report requires a simulation with known labels')
  df=dataset(p);rr=results(p);n=len(df);total=int((df.included==1).sum());found=int((rr.label==1).sum());recall=found/total
  ur=unique_results(p);group_truth=df[df.record_id==df.group_id];gt=int((group_truth.included==1).sum())
  return {'project_id':project_id,'records':n,'screened_records_including_priors':len(rr),'known_relevant_records':total,'found_relevant_records':found,'recall_on_known_labels':recall,'fraction_screened':len(rr)/n,'work_saved_over_random_at_observed_recall':recall-len(rr)/n,'unique_groups':len(group_truth),'screened_groups':len(ur),'group_recall':int((ur.label==1).sum())/gt,'configuration':json.loads((p.project_path/'hermes-simulation.json').read_text()),'limitation':'Synthetic or historical ground truth only; not a guarantee for an unlabelled real review. Priors are counted in screening cost.'}
@op('compare_decisions','Сравнить текущие решения с исходными метками для режима проверки; согласие не доказывает правильность критериев.',{'project_id':S},['project_id'])
def compare_decisions(project_id):
 with project(project_id) as p:
  df=dataset(p).merge(results(p)[['record_id','label']],on='record_id');df=df[df.included.notna()&df.label.notna()]
  if len(df)==0:raise ValueError('No comparable source and current labels')
  from sklearn.metrics import cohen_kappa_score
  a=df.included.astype(int);b=df.label.astype(int)
  k=float(cohen_kappa_score(a,b)) if len(set(a)|set(b))>1 else None
  return {'compared_records':len(df),'agreements':int((a==b).sum()),'disagreements':clean(df[a!=b]),'cohen_kappa':k,'limitation':'No claim of blinded or independent review; input labels may themselves be wrong'}
@op('set_review_status','Отметить обзор завершённым либо возобновить; это не подтверждает полноту найденных исследований.',{'project_id':S,'status':enum('review','finished'),'reason':S},['project_id','status','reason'])
def set_review_status(project_id,status,reason):
 with project(project_id) as p:p.update_review(status=status);event(p,'status',{'status':status,'reason':reason});return {'status':status,'progress':stats(p)}
@op('plot_progress','Создать изображение накопленного числа включённых записей по порядку подтверждённых решений.',{'project_id':S},['project_id'])
def plot_progress(project_id):
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 with project(project_id) as p:
  rr=unique_results(p);out=output(project_id+'-progress','.png');fig,ax=plt.subplots(figsize=(7,4));ax.step(np.arange(1,len(rr)+1),rr.label.astype(int).cumsum(),where='post');ax.set(xlabel='Просмотренные уникальные группы (с начальными примерами)',ylabel='Отмечено релевантными',title='ASReview: '+project_id);ax.grid(alpha=.2);fig.tight_layout();fig.savefig(out,dpi=150);plt.close(fig);return {'image_path':str(out),'screened_groups':len(rr),'limitation':'Review decisions over time, not estimated recall'}
@op('read_documentation','Прочитать ограниченный фрагмент сохранённой официальной инструкции ASReview 3.0.8.',{'document':S,'offset':I,'length':integer(100,15000)},['document'])
def read_documentation(document,offset=0,length=6000):
 base=ROOT/'источники';p=(base/document).resolve()
 if not p.is_relative_to(base) or p.suffix not in ['.rst','.md','.ipynb'] or not p.is_file():raise ValueError('Use an existing documentation file under источники, e.g. lab/progress.rst')
 s=p.read_text();return {'document':document,'text':s[offset:offset+length],'chars_total':len(s),'has_more':offset+length<len(s),'source_version':'3.0.8','reading_level':'Only returned documentation fragment'}
@op('create_demo','Создать отдельный синтетический набор и проект для проверки интерфейса; научных публикаций в нём нет.',{'project_id':S},['project_id'])
def create_demo(project_id):
 rows=[]
 for i in range(24):
  relevant=i%3==0
  title=(['Feedback and student learning','Обратная связь и обучение студентов'][i%2] if relevant else ['Warehouse inventory logistics','Техническое обслуживание двигателей'][i%2])+' '+str(i)
  abstract=('Synthetic study on educational feedback and learning outcomes. Синтетическое описание обратной связи в обучении.' if relevant else 'Synthetic document about machines, stock planning and logistics. Синтетическое описание оборудования и склада.')
  rows.append({'title':title,'abstract':abstract,'included':1 if relevant else 0,'year':2026})
 out=output(project_id+'-truth','.csv');pd.DataFrame(rows).to_csv(out,index=False)
 partial=pd.DataFrame(rows);partial.loc[2:,'included']=pd.NA;partial.included=partial.included.astype('Int64');fp=output(project_id+'-partial','.csv');partial.to_csv(fp,index=False)
 res=create_project(project_id,str(fp));
 with project(project_id) as p:dump(p.project_path/'synthetic.json',{'true_labels':str(out),'description':'24 invented rows, no publications, tests only'})
 set_protocol(project_id,{'question':'Synthetic connection test: educational feedback','include':['Educational feedback and learning outcomes'],'exclude':['Warehouse or machinery topics'],'stage':'title_abstract','stop_rule':'No early stop in connection test','reviewer_policy':'Only synthetic_test decisions; no claims about real literature'})
 return {'project_id':project_id,'truth_file':str(out),'partially_labelled_file':str(fp),'progress':res,'synthetic':True}
def call(name,args=None):
 args=args or {};start=time.monotonic()
 try:
  if name not in OPS:raise ValueError('Unknown ASReview method')
  Draft202012Validator(OPS[name]['input_schema']).validate(args)
  with FileLock(ROOT/'config/bridge.lock',timeout=600),contextlib.redirect_stdout(sys.stderr):result=OPS[name]['fn'](**args)
  return clean({'ok':True,'provider':'Local ASReview','operation':name,'elapsed_seconds':round(time.monotonic()-start,3),**result})
 except Exception as e:
  token=uuid.uuid4().hex;dump(ROOT/'checks'/('error-'+token+'.json'),{'operation':name,'type':type(e).__name__,'error':str(e)})
  return {'ok':False,'provider':'Local ASReview','operation':name,'error_type':type(e).__name__,'error':str(e)[:1100],'diagnostic_file':str(ROOT/'checks'/('error-'+token+'.json'))}
