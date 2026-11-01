"""PubMed/PMC for isolated Hermes BN; reuse the supplied literature helpers."""
import csv,fcntl,importlib.util,io,json,os,re,threading,time,uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import requests
from dotenv import dotenv_values
from jsonschema import Draft7Validator
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
VENDOR=ROOT/'vendor/life-sciences-literature'
def load(name,relative):
 spec=importlib.util.spec_from_file_location(name,VENDOR/relative);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
entrez=load('bn_ncbi_entrez','skills/ncbi-entrez-skill/scripts/ncbi_entrez.py')
pmc=load('bn_ncbi_pmc','skills/ncbi-pmc-skill/scripts/ncbi_pmc.py')
from literature_source_contract import apply_source_contract
LOCAL=threading.local()
CACHE={}

def now():return datetime.now(ZoneInfo('Asia/Dubai')).isoformat()
def key():
 p=ROOT/'credentials.env'
 if not p.exists():return None
 if p.stat().st_mode & 0o077:raise ValueError('credentials.env должен иметь права 0600.')
 v=dotenv_values(p,interpolate=False).get('NCBI_API_KEY')
 if v and re.search(r'[\s\x00-\x1f\x7f]',str(v).strip()):raise ValueError('Ключ содержит недопустимые символы.')
 return str(v).strip() if v else None

def common(params):
 if any(k in params for k in ['api_key','email','tool']):raise ValueError('Контакт и ключ берутся из собственных настроек, а не параметров инструмента.')
 c=json.loads((ROOT/'config/contact.json').read_text());out={**params,'tool':c['tool'],'email':c['email']}
 if key():out['api_key']=key()
 return out
entrez._ncbi_common_params=common
pmc._ncbi_common_params=common

def request(method,url,**kwargs):
 host=urlsplit(url).hostname
 if host not in {'eutils.ncbi.nlm.nih.gov','pmc-oa-opendata.s3.amazonaws.com','www.ncbi.nlm.nih.gov'}:raise ValueError('Запрос за пределами разрешённых служб NCBI/PMC.')
 if urlsplit(url).scheme!='https':raise ValueError('Нужен HTTPS.')
 kwargs.setdefault('timeout',(10,35));kwargs.setdefault('allow_redirects',False)
 lock=ROOT/'config/request.lock';stamp=ROOT/'config/last-request.txt'
 with lock.open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  delay=(0.12 if key() else 0.4)-(time.time()-float(stamp.read_text())) if stamp.exists() else 0
  if delay>0:time.sleep(delay)
  stamp.write_text(str(time.time()));r=requests.request(method,url,**kwargs)
 LOCAL.response=r
 return r
class Session:
 def get(self,url,**kwargs):return request('GET',url,**kwargs)
 def close(self):pass
class Transport:
 RequestException=requests.RequestException
 Session=Session
 @staticmethod
 def get(url,**kwargs):return request('GET',url,**kwargs)
entrez.requests=Transport
pmc.requests=Transport


def text(node):return re.sub(r'\s+',' ',''.join(node.itertext())).strip() if node is not None else ''
def fetch_records(content):
 root=ET.fromstring(content);out=[]
 for a in root:
  if a.tag not in {'PubmedArticle','PubmedBookArticle'}:continue
  ids={n.attrib.get('IdType'):text(n) for n in a.findall('./PubmedData/ArticleIdList/ArticleId')+a.findall('./PubmedBookData/ArticleIdList/ArticleId')}
  pub=a.find('.//Journal/JournalIssue/PubDate');date=' '.join(text(n) for n in pub) if pub is not None else ''
  year=text(pub.find('Year')) if pub is not None else ''
  if not year:
   found=re.search(r'\b(18|19|20)\d{2}\b',date);year=found.group(0) if found else None
  abstract=[{'label':n.attrib.get('Label'),'text':text(n)} for n in a.findall('.//Abstract/AbstractText')]
  authors=[{'last_name':text(n.find('LastName')),'fore_name':text(n.find('ForeName')),'name':text(n.find('LastName'))+' '+text(n.find('ForeName')) if n.find('LastName') is not None else text(n.find('CollectiveName')),'affiliations':[text(v) for v in n.findall('.//Affiliation')]} for n in a.findall('./MedlineCitation/Article/AuthorList/Author')+a.findall('./BookDocument/AuthorList/Author')]
  out.append({'pmid':text(a.find('.//PMID')),'title':text(a.find('.//ArticleTitle')) or text(a.find('.//BookTitle')),'journal':text(a.find('.//Journal/Title')),'volume':text(a.find('.//Journal/JournalIssue/Volume')),'issue':text(a.find('.//Journal/JournalIssue/Issue')),'pages':text(a.find('.//Pagination/MedlinePgn')),'year':int(year) if year else None,'bibliographic_year':int(year) if year else None,'year_scope':'PubMed bibliographic issue year; electronic date is separate','publication_date':date,'article_dates':[{**n.attrib,'date':'-'.join(text(c) for c in n)} for n in a.findall('.//ArticleDate')],'doi':ids.get('doi'),'pmcid':ids.get('pmc'),'authors':authors,'abstract':abstract,'publication_types':[text(n) for n in a.findall('.//PublicationType')],'mesh_terms':[text(n.find('DescriptorName')) for n in a.findall('.//MeshHeading')],'keywords':[text(n) for n in a.findall('.//Keyword')],'corrections':[{'type':n.attrib.get('RefType'),'pmid':text(n.find('PMID')),'citation':text(n.find('RefSource'))} for n in a.findall('.//CommentsCorrections')],'conflicts':text(a.find('.//CoiStatement')),'canonical_url':'https://pubmed.ncbi.nlm.nih.gov/'+text(a.find('.//PMID'))+'/','reading_level':'metadata and abstract, not full article'})
 return out

ENDPOINTS={'pubmed_search':'esearch','pubmed_summary':'esummary','pubmed_fetch':'efetch','pubmed_links':'elink','pubmed_info':'einfo','pubmed_spell':'espell','pubmed_history':'epost','pubmed_citation_match':'ecitmatch'}
BASE={'term':{'type':'string'},'id':{'type':'string'},'retmax':{'type':'integer','minimum':0,'maximum':10000},'retstart':{'type':'integer','minimum':0},'sort':{'type':'string'},'datetype':{'type':'string','enum':['pdat','edat','mdat']},'mindate':{'type':'string'},'maxdate':{'type':'string'},'reldate':{'type':'integer','minimum':1},'usehistory':{'type':'string','enum':['y','n']},'WebEnv':{'type':'string'},'query_key':{'type':'string'},'linkname':{'type':'string','enum':['pubmed_pubmed','pubmed_pubmed_citedin','pubmed_pubmed_refs']},'cmd':{'type':'string','enum':['neighbor','neighbor_score','neighbor_history','llinks','prlinks','acheck']},'bdata':{'type':'string'},'version':{'type':'string'}}
FIELDS={'pubmed_search':['term','retmax','retstart','sort','datetype','mindate','maxdate','reldate','usehistory','WebEnv'],'pubmed_summary':['id','WebEnv','query_key','retmax','retstart','version'],'pubmed_fetch':['id','WebEnv','query_key','retmax','retstart'],'pubmed_links':['id','linkname','cmd','WebEnv','query_key'],'pubmed_info':['version'],'pubmed_spell':['term'],'pubmed_history':['id','WebEnv'],'pubmed_citation_match':['bdata']}
DESCRIPTIONS={'pubmed_search':'Поиск PubMed: PMID, число совпадений, перевод запроса, предупреждения и история. Не полный текст.','pubmed_summary':'Краткая библиографическая запись по PMID или сохранённой истории.','pubmed_fetch':'Полные библиографические записи и аннотации, MeSH и связи исправлений. Не полный текст статьи.','pubmed_links':'Похожие, цитируемые или цитирующие записи PubMed. Сеть может быть неполной.','pubmed_info':'Поля и допустимые связи базы PubMed.','pubmed_spell':'Подсказки исправления поискового запроса.','pubmed_history':'Временная история PMID на сервере NCBI для пакетного получения.','pubmed_citation_match':'Разрешение строк journal|year|volume|page|author|key через ECitMatch.'}
OPERATIONS={n:{'description':DESCRIPTIONS[n],'input_schema':{'type':'object','properties':{k:BASE[k] for k in FIELDS[n]},'required':['term'] if n in {'pubmed_search','pubmed_spell'} else ['id'] if n=='pubmed_history' else ['bdata'] if n=='pubmed_citation_match' else [],'additionalProperties':False}} for n in ENDPOINTS}
for n,d,props,required in [
 ('pmc_metadata','Разрешить PMCID/PMID/DOI и проверить актуальную версию, лицензию и ссылки PMC Cloud. Не чтение статьи.',{'identifier':{'type':'string'}},['identifier']),
 ('pmc_sections','Список разделов и таблиц доступного JATS XML с версией и лицензией.',{'identifier':{'type':'string'}},['identifier']),
 ('pmc_read','Прочитать заданный раздел или ограниченный фрагмент текущего полного текста PMC.',{'identifier':{'type':'string'},'section_id':{'type':'string'},'offset':{'type':'integer','minimum':0},'max_chars':{'type':'integer','minimum':100,'maximum':50000}},['identifier']),
 ('pmc_table','Прочитать таблицу по идентификатору или номеру: строки, подпись и примечания.',{'identifier':{'type':'string'},'table_id':{'type':'string'}},['identifier','table_id']),
 ('pmc_pdf_status','Проверить доступность PDF и первые байты без сохранения и без заявления о чтении.',{'identifier':{'type':'string'}},['identifier']),
 ('pubmed_export','Создать местную производную библиографию CSV, RIS или BibTeX по данным PubMed.',{'id':{'type':'string'},'format':{'type':'string','enum':['csv','ris','bibtex']},'date_basis':{'type':'string','enum':['bibliographic','electronic']}},['id','format']),
 ('service_status','Проверить режим и настройки без раскрытия ключа и контактной почты.',{},[])]:OPERATIONS[n]={'description':d,'input_schema':{'type':'object','properties':props,'required':required,'additionalProperties':False}}

for _name in ['pubmed_summary','pubmed_fetch']:
 OPERATIONS[_name]['input_schema']['anyOf']=[{'required':['id']},{'required':['WebEnv','query_key']}]
OPERATIONS['pubmed_links']['input_schema']['required']=['id']
OPERATIONS['pubmed_links']['input_schema']['properties']['max_links']={'type':'integer','minimum':1,'maximum':10000}
for _field in ['id','term','bdata']:BASE[_field]['minLength']=1


def pubmed(name,args):
 endpoint=ENDPOINTS[name];params={'db':'pubmed',**args};max_links=params.pop('max_links',20)
 if name=='pubmed_search':params.setdefault('retmax',10)
 if name in {'pubmed_search','pubmed_summary','pubmed_info','pubmed_links'}:params['retmode']='json'
 else:params['retmode']='xml'
 if name=='pubmed_links':params['dbfrom']='pubmed';params.setdefault('linkname','pubmed_pubmed')
 if name=='pubmed_summary':params.setdefault('version','2.0')
 r=entrez.execute({'endpoint':endpoint,'params':params,'response_format':'text' if name=='pubmed_citation_match' else 'auto','max_items':20,'max_depth':10,'save_raw':False})
 if not r.get('ok'):return r
 response=LOCAL.response
 if response.text.lstrip().startswith('{'):
  _data=response.json()
  if _data.get('error') or _data.get('ERROR'):return {'ok':False,'error':{'code':'upstream_error','message':str(_data.get('error') or _data.get('ERROR'))},'sources':[],'checked_sources':r.get('checked_sources',[])}
 if name=='pubmed_info':
  info=response.json().get('einforesult',{}).get('dbinfo',[])
  r['database_info']=[{'name':i.get('dbname'),'count':i.get('count'),'last_update':i.get('lastupdate'),'fields':i.get('fieldlist'),'pubmed_links':[l for l in i.get('linklist',[]) if l.get('name','').startswith('pubmed_pubmed')]} for i in info]
 elif name=='pubmed_fetch':
  records=fetch_records(response.content);r={'ok':True,'source':'ncbi-entrez','endpoint':endpoint,'database':'pubmed','records':records,'record_count_returned':len(records),'reading_level':'metadata and abstracts','warnings':[],'raw_output_path':None};r=apply_source_contract(r,'ncbi-entrez-skill',response.url)
 elif name=='pubmed_search':
  s=response.json().get('esearchresult',{});r['search']={k:s[k] for k in ['count','retmax','retstart','idlist','querytranslation','querykey','webenv','warninglist','errorlist'] if k in s}
  if int(s.get('count',0))>10000:r['warnings'].append('PubMed имеет предел 10000 PMID для одной выдачи; нужен отдельный план разбиения, первая страница не равна всем результатам.')
 elif name=='pubmed_links':
  r['links']=[{'source_ids':v.get('ids',[]),'relation':d.get('linkname'),'target_ids':d.get('links',[])[:max_links],'count_in_response':len(d.get('links',[])),'returned':min(len(d.get('links',[])),max_links),'truncated':len(d.get('links',[]))>max_links,'coverage':'links known to this PubMed index, not all worldwide citations'} for v in response.json().get('linksets',[]) for d in v.get('linksetdbs',[]) if d.get('dbto')=='pubmed']
 elif name=='pubmed_summary':
  s=response.json().get('result',{});r['records']=[s[i] for i in s.get('uids',[]) if i in s];r.pop('summary',None)
 return r

def metadata(identifier):return pmc.execute({'params':{'id':identifier},'max_items':10,'save_raw':False})
def document(identifier):
 c=CACHE.get(identifier)
 if c and time.time()-c[0]<300:return c[1]
 m=metadata(identifier)
 if not m.get('ok'):raise ValueError(m.get('error',{}).get('message','PMC недоступен.'))
 records=m.get('records',[])
 if not records:raise ValueError('Для идентификатора не найден текущий набор статьи PMC Cloud.')
 if len({r['pmcid'] for r in records})>1 or m.get('truncated'):raise ValueError('Нужен однозначный PMCID и версия.')
 rec=max(records,key=lambda x:int(x.get('version') or 0))
 if not rec.get('xml_url'):raise ValueError('Текст JATS XML недоступен в текущей версии.')
 if not (rec.get('is_pmc_openaccess') or rec.get('is_manuscript')):raise ValueError('Статья не входит в доступный набор PMC для автоматического чтения.')
 r=request('GET',rec['xml_url']);r.raise_for_status();root=ET.fromstring(r.content)
 if len(CACHE)>=32:CACHE.pop(min(CACHE,key=lambda k:CACHE[k][0]))
 data={'metadata':rec,'root':root,'retrieved_at':now(),'checked_sources':m.get('checked_sources',[])};CACHE[identifier]=(time.time(),data);return data

def pmc_reading(name,args):
 d=document(args['identifier']);rec=d['metadata'];root=d['root'];base={'ok':True,'source':'PMC Cloud JATS XML','pmcid':rec['pmcid'],'version':rec['version'],'license':rec['license_code'],'metadata_retraction_flag':rec['is_retracted'],'retrieved_at':d['retrieved_at'],'canonical_url':rec['canonical_url'],'checked_sources':d['checked_sources']}
 if name=='pmc_sections':
  base['sections']=[{'id':s.attrib.get('id'),'title':text(s.find('title')),'characters':len(text(s))} for s in root.findall('.//body//sec')]
  base['tables']=[{'id':t.attrib.get('id'),'label':text(t.find('label')),'caption':text(t.find('caption'))} for t in root.findall('.//table-wrap')];base['reading_level']='structure only';base['sources']=[];return base
 if name=='pmc_pdf_status':
  if not rec.get('pdf_url'):return {**base,'available':False,'sources':[]}
  r=request('GET',rec['pdf_url'],stream=True)
  try:head=next(r.iter_content(8),b'');base.update({'available':r.status_code==200 and head.startswith(b'%PDF'),'http_status':r.status_code,'content_type':r.headers.get('Content-Type'),'full_pdf_read':False,'sources':[]})
  finally:r.close()
  return base
 if name=='pmc_table':
  q=args['table_id'];tables=root.findall('.//table-wrap');table=next((t for t in tables if t.attrib.get('id')==q or text(t.find('label')).lower()==q.lower() or re.sub(r'\D','',text(t.find('label')))==q),None)
  if table is None:raise ValueError('Таблица не найдена; сначала pmc_sections.')
  base.update({'table_id':table.attrib.get('id'),'label':text(table.find('label')),'caption':text(table.find('caption')),'rows':[[text(c) for c in row if c.tag in {'td','th'}] for row in table.findall('.//tr')],'footnotes':text(table.find('table-wrap-foot')),'reading_level':'one table, caption and footnotes'})
 else:
  node=root.find('body')
  if args.get('section_id'):
   node=next((s for s in root.findall('.//sec') if s.attrib.get('id')==args['section_id']),None)
   if node is None:raise ValueError('Раздел не найден; сначала pmc_sections.')
  full=text(node);offset=args.get('offset',0);cap=args.get('max_chars',12000)
  base.update({'text':full[offset:offset+cap],'offset':offset,'returned_characters':len(full[offset:offset+cap]),'total_characters':len(full),'has_more':offset+cap<len(full),'section_id':args.get('section_id'),'scope':'selected JATS section' if args.get('section_id') else 'JATS body, excluding front and back matter','reading_level':'bounded fulltext fragment; not necessarily the whole article'})
 base['sources']=[{'kind':'evidence','supports_claim':True,'source':'PubMed Central','canonical_url':rec['canonical_url'],'pmcid':rec['pmcid'],'version':rec['version'],'reading_level':base['reading_level']}];return base


def export(args):
 r=pubmed('pubmed_fetch',{'id':args['id']})
 if not r.get('ok'):return r
 records=r['records'];fmt=args['format'];out=io.StringIO();warnings=[]
 for record in records:
  electronic=next((d['date'] for d in record['article_dates'] if d.get('DateType')=='Electronic'),None)
  if electronic and int(electronic[:4])!=record['bibliographic_year']:warnings.append({'pmid':record['pmid'],'bibliographic_year':record['bibliographic_year'],'electronic_date':electronic,'action':'Проверить год у издателя и выбранный стиль.'})
  if args.get('date_basis')=='electronic' and electronic:record['year']=int(electronic[:4])
 if fmt=='csv':
  w=csv.DictWriter(out,fieldnames=['pmid','title','year','journal','doi','canonical_url']);w.writeheader();w.writerows({k:r.get(k) for k in w.fieldnames} for r in records)
 elif fmt=='ris':
  for r in records:
   out.write('TY  - JOUR\nTI  - '+r['title']+'\n');out.writelines('AU  - '+(a['last_name']+', '+a['fore_name'] if a['last_name'] else a['name'])+'\n' for a in r['authors']);out.write('PY  - '+str(r['year'] or '')+'\nJO  - '+r['journal']+'\n');out.write(('DO  - '+r['doi']+'\n') if r['doi'] else '');out.write('UR  - '+r['canonical_url']+'\nER  - \n\n')
 else:
  for r in records:
   fields={'title':r['title'],'author':' and '.join((a['last_name']+', '+a['fore_name'] if a['last_name'] else a['name']) for a in r['authors']),'year':r['year'],'journal':r['journal'],'volume':r['volume'],'number':r['issue'],'pages':r['pages'],'doi':r['doi'],'url':r['canonical_url']};out.write('@article{pmid'+r['pmid']+',\n'+',\n'.join('  '+k+' = {'+str(v).replace('\\','\\textbackslash{}').replace('%','\\%').replace('&','\\&')+'}' for k,v in fields.items() if v)+'\n}\n')
 p=ROOT/'exports'/('pubmed-'+uuid.uuid4().hex+'.'+('bib' if fmt=='bibtex' else fmt));p.write_text(out.getvalue());p.chmod(0o600)
 return {'ok':True,'source':'locally formatted from PubMed bibliographic records','file':str(p),'format':fmt,'records':len(records),'sources':r.get('sources',[]),'checked_sources':r.get('checked_sources',[]),'not_raw_ncbi_output':True,'date_basis':args.get('date_basis','bibliographic'),'date_warnings':warnings}

def call(name,args):
 if name not in OPERATIONS:raise ValueError('Нет такого инструмента.')
 errors=list(Draft7Validator(OPERATIONS[name]['input_schema']).iter_errors(args))
 if errors:raise ValueError('; '.join(e.message for e in errors[:3]))
 if name in ENDPOINTS:r=pubmed(name,args)
 elif name=='pmc_metadata':r=metadata(args['identifier'])
 elif name=='pubmed_export':r=export(args)
 elif name=='service_status':r={'ok':True,'mode':'with_key' if key() else 'without_key','api_key_saved':bool(key()),'contact_configured':True,'request_interval':0.12 if key() else 0.4,'raw_responses_saved':False,'disclaimer':'https://www.ncbi.nlm.nih.gov/home/about/policies/','corpus':'PubMed bibliographic records; PMC available fulltexts'}
 else:r=pmc_reading(name,args)
 r={**r,'tool':name,'retrieved_at_client':now(),'api_key_used':bool(key())}
 if key():r=json.loads(json.dumps(r,ensure_ascii=False).replace(key(),'[скрыто]'))
 return r
