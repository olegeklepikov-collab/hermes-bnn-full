"""Official Crossref read APIs for the independent Hermes BN runtime."""
import csv,fcntl,hashlib,html,io,json,os,re,time,uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote,urlsplit,unquote,urlencode
from zoneinfo import ZoneInfo
import httpx
from jsonschema import Draft7Validator
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
BASE='https://api.crossref.org/v1'
FORMATS={'csl-json':'application/vnd.citationstyles.csl+json','bibtex':'application/x-bibtex',
 'ris':'application/x-research-info-systems','bibliography':'text/x-bibliography',
 'rdf':'application/rdf+xml','turtle':'text/turtle',
 'unixref':'application/vnd.crossref.unixref+xml','unixsd':'application/vnd.crossref.unixsd+xml'}
DATE_FIELDS=['published','published-online','published-print','issued','posted','accepted','created','deposited','indexed']
ENTITY_TYPES=['journals','members','funders','prefixes','types','licenses']

def now():return datetime.now(ZoneInfo('Asia/Dubai')).isoformat()
def settings():return json.loads((ROOT/'config/settings.json').read_text())
def normalize_doi(value):
    value=value.strip()
    if value.lower().startswith(('https://doi.org/','http://doi.org/','https://dx.doi.org/','http://dx.doi.org/')):
        parsed=urlsplit(value)
        if parsed.query or parsed.fragment:raise ValueError('Provide the DOI without URL query or fragment')
        value=unquote(parsed.path.lstrip('/'))
    elif value.lower().startswith('doi:'):value=value[4:].strip()
    if len(value)>1024 or not re.fullmatch(r'10\.\d{4,9}/[^\s\x00-\x1f\x7f]+',value):raise ValueError('Invalid DOI syntax; do not trim meaningful suffix punctuation')
    return value.lower()
def doi_path(value):return quote(normalize_doi(value),safe='/')

class APIError(Exception):
    def __init__(self,message,status=None,retry_after=None,diagnostic_file=None):
        super().__init__(message);self.status=status;self.retry_after=retry_after;self.diagnostic_file=diagnostic_file

def atomic_json(path,value):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x') as f:json.dump(value,f,ensure_ascii=False)
    temporary.chmod(0o600);temporary.replace(path)

def request(url,params=None,accept='application/json',cache=True,method='GET'):
    if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in {'api.crossref.org','doi.crossref.org','oai.crossref.org'}:
        raise ValueError('Only official Crossref HTTPS destinations are allowed')
    c=settings();p=dict(params or {})
    if c.get('email') and urlsplit(url).hostname=='api.crossref.org':p['mailto']=c['email']
    safe_params={k:v for k,v in p.items() if k not in ('mailto','pid','usr','qdata')}
    source=url+('?' + urlencode(safe_params) if safe_params else '')
    key=hashlib.sha256(json.dumps([url,p,accept,method],sort_keys=True).encode()).hexdigest()
    cached=ROOT/'cache'/(key+'.json');gate=ROOT/'config/transport-state.json'
    with (ROOT/'config/request.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if cache and method=='GET' and cached.exists():
            value=json.loads(cached.read_text())
            if time.time()-value['saved_epoch']<c['cache_ttl_seconds']:
                return {**value['result'],'cache_hit':True}
        state=json.loads(gate.read_text()) if gate.exists() else {}
        remaining=state.get('blocked_until',0)-time.time()
        if remaining>0:raise APIError('Crossref requested a pause; no request sent',429,round(remaining,2))
        interval=max(c['minimum_interval_seconds'] if c.get('email') else 1.05,state.get('interval',0))
        delay=interval-(time.time()-state.get('last_finished',0))
        if delay>0:time.sleep(delay)
        with httpx.Client(timeout=httpx.Timeout(45,connect=10),follow_redirects=False) as client:
            r=client.request(method,url,params=p,headers={'User-Agent':c['user_agent'],'Accept':accept})
        state['last_finished']=time.time()
        headers={k:r.headers[k] for k in ['x-api-pool','x-rate-limit-limit','x-rate-limit-interval','x-concurrency-limit','retry-after'] if k in r.headers}
        limit=r.headers.get('x-rate-limit-limit');duration=r.headers.get('x-rate-limit-interval','')
        if limit and re.fullmatch(r'[\d.]+s',duration):state['interval']=float(duration[:-1])/float(limit)*1.05
        if r.status_code==429:
            try:retry=float(r.headers.get('retry-after','10'))
            except ValueError:retry=10
            state['blocked_until']=time.time()+max(retry,1)
        atomic_json(gate,state)
        if r.status_code>=400:
            diagnostic=ROOT/'checks'/('upstream-error-'+uuid.uuid4().hex+'.json')
            diagnostic.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(diagnostic,{'http_status':r.status_code,'source_url':source,'retrieved_at':now(),'headers':headers,'body':r.text})
            try:
                error=r.json();detail=error.get('message',error) if isinstance(error,dict) else error
                if isinstance(detail,dict):detail={k:detail[k] for k in ('name','description','message','code') if k in detail} or detail
                brief=json.dumps(detail,ensure_ascii=False) if not isinstance(detail,str) else detail
            except (ValueError,TypeError):brief=r.text
            raise APIError(brief[:800],r.status_code,r.headers.get('retry-after'),str(diagnostic))
        result={'http_status':r.status_code,'source_url':source,'retrieved_at':now(),'cache_hit':False,
                'response_limits':headers,'content_type':r.headers.get('content-type'),'email_sent':bool(c.get('email'))}
        if method=='HEAD':result['exists']=True
        elif 300<=r.status_code<400:result['location']=r.headers.get('location')
        elif 'json' in r.headers.get('content-type',''):
            data=r.json()
            if isinstance(data,dict) and data.get('status')=='error':raise APIError(str(data.get('message')),r.status_code)
            result['data']=data
        else:result['text']=r.text
        if cache and r.status_code==200 and method=='GET':atomic_json(cached,{'saved_epoch':time.time(),'result':result})
        return result

def message(result):
    data=result['data'];return data.get('message',data) if isinstance(data,dict) else data
def work(doi,cache=True):
    result=request(BASE+'/works/'+doi_path(doi),cache=cache)
    result['record']=message(result);result.pop('data',None)
    result['reading_level']='Deposited/enriched bibliographic metadata and abstract if present; no article full text'
    result['date_fields']={k:result['record'][k] for k in DATE_FIELDS if k in result['record']}
    return result

def works_path(args):
    scope=args.get('scope','all')
    if scope=='all':return BASE+'/works'
    if scope not in ('journals','members','funders','prefixes','types'):raise ValueError('Invalid works scope')
    identifier=args.get('scope_id','').strip()
    if not identifier or '/' in identifier or '?' in identifier or '#' in identifier:raise ValueError('scope_id must be an ISSN, numeric member/funder ID, DOI prefix or work type')
    return BASE+'/'+scope+'/'+quote(identifier,safe='')+'/works'

def query_params(args):
    p={k:args[k] for k in ('query','rows','offset','cursor','sort','order','sample') if k in args}
    p.setdefault('rows',settings()['default_page_rows'])
    if 'sample' in p:
        if any(k in p for k in ('offset','cursor')):raise ValueError('sample cannot be combined with offset or cursor')
        p.pop('rows',None)
    if 'cursor' in p and ('offset' in p or p['rows']==0):raise ValueError('cursor requires positive rows and cannot be combined with offset')
    for k,v in args.get('query_fields',{}).items():
        if k not in ('bibliographic','author','editor','chair','translator','contributor','affiliation','container-title'):
            raise ValueError('Unsupported field query; use bibliographic rather than deprecated query.title')
        p['query.'+k]=v
    filters=args.get('filters',[])
    if filters:
        if any(',' in f or ':' not in f or '\n' in f for f in filters):raise ValueError('Supply separate name:value filters; use repeated names for OR')
        p['filter']=','.join(filters)
    if args.get('select'):p['select']=','.join(args['select'])
    if args.get('facets'):p['facet']=','.join(k+':'+str(v) for k,v in args['facets'].items())
    return p

def search(args):
    p=query_params(args);result=request(works_path(args),p,cache=not ('cursor' in p or 'sample' in p))
    data=message(result);items=data.get('items',[]);result.pop('data',None)
    result.update(records=items,total_results=data.get('total-results'),returned=len(items),
                  query=data.get('query'),facets=data.get('facets',{}),next_cursor=data.get('next-cursor'),
                  requested_parameters={k:v for k,v in p.items() if k!='mailto'},
                  reading_level='Returned bibliographic metadata/abstracts; no full article text')
    rows=p.get('rows',p.get('sample',10))
    result['pagination']={'more_may_exist':bool(rows and len(items)==rows),
        'stop_when':'Returned items fewer than requested rows; cursor presence alone does not prove another page',
        'snapshot_consistency':'Results can change while paging; bound index dates and deduplicate DOI for a complete extraction'}
    return result

def entity_id(kind,value):
    value=value.strip()
    if kind in ('members','funders') and not value.isdigit():raise ValueError('Use a numeric registry identifier')
    if kind=='prefixes' and not re.fullmatch(r'10\.\d{4,9}',value):raise ValueError('Invalid DOI prefix')
    if kind=='journals' and not re.fullmatch(r'\d{4}-?\d{3}[\dXx]',value):raise ValueError('Invalid ISSN')
    if kind=='types' and not re.fullmatch(r'[a-z-]+',value):raise ValueError('Invalid work type')
    return quote(value,safe='')

def xml_summary(body):
    tree=ET.fromstring(body)
    nodes=[]
    for n in tree.iter():
        tag=n.tag.rsplit('}',1)[-1]
        if tag in ('doi','article_title','journal_title','year','query','doi_record','msg'):
            entry={'element':tag,'attributes':n.attrib}
            if tag not in ('doi_record','query'):entry['text']=' '.join(''.join(n.itertext()).split())
            nodes.append(entry)
    return nodes

def save_export(name,body):
    if Path(name).name!=name or name in ('.','..'):raise ValueError('Use a bare output filename')
    path=ROOT/'exports'/name
    with path.open('x') as f:f.write(body)
    path.chmod(0o600);return str(path)

def execute(name,args):
    if name=='service_status':
        result=request(BASE+'/types',cache=False);c=settings()
        return {**result,'configured_mode':c['mode'],'api_key_used':False,'technical_contact_configured':bool(c.get('email')),
            'cross_process_concurrency':1,'minimum_interval_seconds':c['minimum_interval_seconds'],
            'cache_ttl_seconds':c['cache_ttl_seconds'],'types_returned':len(message(result).get('items',[])),
            'fulltext_service':False,'beta_data_citations':True,'private_library_or_write_access':False}
    if name=='works_search':return search(args)
    if name=='work_get':return work(args['doi'],cache=not args.get('refresh',False))
    if name=='works_batch':
        entries=[]
        for doi in args['dois']:
            try:entries.append({'ok':True,**work(doi)})
            except Exception as e:
                entries.append({'ok':False,'doi':doi,'error':str(e),'http_status':getattr(e,'status',None)})
                if getattr(e,'status',None) in (429,500,502,503,504):break
        complete=len(entries)==len(args['dois']) and all(v['ok'] for v in entries)
        return {'ok':complete,'records':entries,'requested':len(args['dois']),'returned':len(entries),
                'all_succeeded':complete,'partial_failure':not complete,
                'reading_level':'Metadata per DOI; individual failures retained; no provider fallback'}
    if name=='bibliographic_match':
        result=search({'query_fields':{'bibliographic':args['citation']},'rows':args.get('rows',5)})
        candidates=[]
        for item in result['records']:
            title=' '.join(item.get('title',[]))
            exact=None
            if args.get('expected_title'):
                canon=lambda x:re.sub(r'\W+',' ',html.unescape(x).casefold()).strip()
                exact=canon(title)==canon(args['expected_title'])
            candidates.append({'doi':item.get('DOI'),'title':title,'author':item.get('author',[]),
                'published':item.get('published'),'score':item.get('score'),'exact_normalized_title':exact})
        result['candidates']=candidates
        result['match_policy']='Search score is not probability or verification. Check DOI, title, authors and date; ambiguous matches remain candidates.'
        return result
    if name=='doi_agency':return request(BASE+'/works/'+doi_path(args['doi'])+'/agency')
    if name=='doi_exists':return request(BASE+'/works/'+doi_path(args['doi']),method='HEAD',cache=False)
    if name in ('work_references','work_relations','work_updates','work_funding','work_licenses_links'):
        result=work(args['doi']);record=result.pop('record');result.pop('date_fields',None)
        result['doi']=record['DOI']
        if name=='work_references':
            refs=record.get('reference',[]);start=args.get('start',0);limit=args.get('limit',25)
            result.update(references=refs[start:start+limit],returned=len(refs[start:start+limit]),
                deposited_reference_entries=len(refs),reported_reference_count=record.get('reference-count'),
                has_more=start+limit<len(refs),start=start,
                cited_by_count=record.get('is-referenced-by-count'),
                coverage='Deposited references and Crossref cited-by count, not complete worldwide citations or citation contexts')
        elif name=='work_relations':
            result.update(relations=record.get('relation',{}),coverage='Deposited/enriched typed relations; absent field does not prove no relation exists')
        elif name=='work_funding':
            result.update(funders=record.get('funder',[]),grants=record.get('award',[]),
                contributors=record.get('author',[]),coverage='Preserve deposited/enriched funder DOI and ROR IDs, awards, ORCID, affiliations and contributor roles; absence is unknown')
        elif name=='work_licenses_links':
            result.update(licenses=record.get('license',[]),fulltext_links=record.get('link',[]),resource=record.get('resource'),
                coverage='Links/license metadata only; no article downloaded or read and no access rights inferred')
        else:
            updates=search({'filters':['updates:'+normalize_doi(args['doi'])],'rows':args.get('rows',10)})
            result.update(update_to=record.get('update-to',[]),updated_by=record.get('updated-by',[]),
                assertions=record.get('assertion',[]),update_policy=record.get('update-policy'),
                update_records=updates['records'],update_records_total=updates['total_results'],update_query_source=updates['source_url'],
                coverage='Publisher and Retraction Watch metadata. No reported update is not proof of no correction/retraction; read any notice before interpreting it')
        return result
    if name=='entities_search':
        kind=args['entity']
        if kind=='prefixes':raise ValueError('No prefix list endpoint; use entity_get')
        p={k:args[k] for k in ('query','rows','offset') if k in args};p.setdefault('rows',10)
        if args.get('filters'):p['filter']=','.join(args['filters'])
        return request(BASE+'/'+kind,p)
    if name=='entity_get':
        kind=args['entity']
        if kind=='licenses':raise ValueError('Use entities_search for the license catalogue')
        return request(BASE+'/'+kind+'/'+entity_id(kind,args['id']))
    if name=='works_facets':return search({**args,'rows':0})
    if name=='works_sample':return search(args)
    if name=='metadata_transform':
        accept=FORMATS[args['format']]
        if args['format']=='bibliography':
            style=args.get('style','apa');locale=args.get('locale','en-US')
            if not re.fullmatch(r'[a-z0-9-]+',style) or not re.fullmatch(r'[a-z]{2}(?:-[A-Z]{2})?',locale):raise ValueError('Invalid CSL style or locale')
            accept+='; style='+style+'; locale='+locale
        # The official unversioned transform route is verified for all eight media types.
        # /v1/transform currently fails for some types despite documented examples.
        result=request('https://api.crossref.org/works/'+doi_path(args['doi'])+'/transform',accept=accept)
        result.update(format=args['format'],reading_level='Bibliographic representation only; conversion can omit or remap fields')
        if args['format'] in ('bibliography','bibtex','ris','csl-json'):
            original=work(args['doi'])['record'];number=original.get('article-number')
            rendered=result.get('text') or json.dumps(result.get('data'),ensure_ascii=False)
            rendered=re.sub(re.escape(original['DOI']),'',rendered,flags=re.I)
            missing=bool(number and not re.search(r'(?<![\w.])'+re.escape(str(number))+r'(?!\w)',rendered))
            result['conversion_check']={'source_article_number':number,'article_number_missing_from_export':missing,
                'scope':'Limited field-presence check, not a complete citation-style audit',
                'warning':'Crossref transformer omitted the article number; retain original metadata and correct the final citation' if missing else None}
        if args.get('output_name'):
            result['output_path']=save_export(args['output_name'],result.get('text') or json.dumps(result.get('data'),ensure_ascii=False,indent=2))
        return result
    if name=='citation_styles':
        result=request(BASE+'/styles');styles=message(result)
        if isinstance(styles,dict):styles=styles.get('items',[])
        result.pop('data',None);filtered=[s for s in styles if args.get('query','').casefold() in str(s).casefold()]
        result.update(styles=filtered[:args.get('limit',25)],matching=len(filtered),total=len(styles),has_more=len(filtered)>args.get('limit',25))
        return result
    if name=='export_records':
        entries=[work(doi) for doi in args['dois']];records=[v['record'] for v in entries]
        fmt=args['format']
        if fmt=='json':body=json.dumps({'provider':'Crossref','retrieved_at':now(),'records':records,'sources':[v['source_url'] for v in entries]},ensure_ascii=False,indent=2)
        else:
            stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['DOI','title','type','published','published_online','published_print','issued','publisher','container_title','volume','issue','page','article_number','cited_by_crossref','source_url'])
            for item,entry in zip(records,entries):
                row=[item.get('DOI'),' | '.join(item.get('title',[])),item.get('type'),*[json.dumps(item.get(k,{}).get('date-parts',[])) for k in ('published','published-online','published-print','issued')],item.get('publisher'),' | '.join(item.get('container-title',[])),item.get('volume'),item.get('issue'),item.get('page'),item.get('article-number'),item.get('is-referenced-by-count'),entry['source_url']]
                writer.writerow(["'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
            body=stream.getvalue()
        return {'output_path':save_export(args['output_name'],body),'format':fmt,'record_count':len(records),
            'source_urls':[v['source_url'] for v in entries],'reading_level':'Metadata export, not article reading','csv_policy':'Formula-like cells escaped; JSON retains original values'}
    if name in ('xml_doi_lookup','xml_citation_match','openurl_lookup'):
        email=settings().get('email')
        if not email:raise ValueError('This interface requires an owner-authorized technical contact')
        fmt=args.get('format','unixsd')
        if name=='xml_doi_lookup':url='https://doi.crossref.org/search/doi';params={'pid':email,'doi':normalize_doi(args['doi']),'format':fmt}
        elif name=='openurl_lookup':
            url='https://doi.crossref.org/openurl';params={'pid':email,'format':fmt}
            if args.get('doi'):params['id']='doi:'+normalize_doi(args['doi'])
            else:
                params.update({k:args[k] for k in ('title','issn','volume','issue','spage','aulast','date','atitle') if k in args})
                if not (('title' in params or 'issn' in params) and ('spage' in params or 'aulast' in params)):raise ValueError('OpenURL matching needs title/ISSN and first page/author')
        else:
            ns='http://www.crossref.org/qschema/2.0';ET.register_namespace('',ns)
            tree=ET.Element('{'+ns+'}query_batch',{'version':'2.0'});head=ET.SubElement(tree,'{'+ns+'}head')
            ET.SubElement(head,'{'+ns+'}email_address').text=email
            ET.SubElement(head,'{'+ns+'}doi_batch_id').text='HermesBN-'+uuid.uuid4().hex
            body=ET.SubElement(tree,'{'+ns+'}body')
            for index,citation in enumerate(args['citations']):
                query=ET.SubElement(body,'{'+ns+'}query',{'key':str(index),'enable-multiple-hits':'true'})
                ET.SubElement(query,'{'+ns+'}unstructured_citation').text=citation
            xml=ET.tostring(tree,encoding='utf-8',xml_declaration=True).decode('utf-8')
            url='https://doi.crossref.org/servlet/query';params={'usr':email,'format':fmt,'qdata':xml}
        result=request(url,params,accept='application/xml')
        if 'text' in result:
            result['metadata_elements']=xml_summary(result['text'])
            result['text']=result['text'].replace(email,'[technical contact]')
            result['metadata_elements']=json.loads(json.dumps(result['metadata_elements']).replace(email,'[technical contact]'))
            bad=[n for n in result['metadata_elements'] if n['element']=='query' and n['attributes'].get('status') in ('malformed','error')]
            if bad:result.update(ok=False,error='Crossref XML rejected the query despite HTTP 200; inspect query status/messages')
        result['reading_level']='XML bibliographic matching/metadata, not full text; match status must be inspected'
        return result
    if name=='data_citations':
        if not settings().get('email'):raise ValueError('Beta service requests an authorized mailto contact')
        mapping={'object_id':'object-id','subject_id':'subject-id','member_id':'member-id','from_created_date':'from-created-date','until_created_date':'until-created-date','rows':'rows','page':'page','relation':'relation'}
        params={mapping[k]:v for k,v in args.items() if k in mapping}
        result=request('https://api.crossref.org/beta/datacitations',params,cache=False)
        result.update(beta=True,coverage='Dataset DOI links deposited in references/relations; beta coverage is incomplete and delayed by about five days; not all inbound scientific citations',reading_level='Data citation relationship metadata only')
        return result
    if name=='oai_discovery':
        verb=args['verb'];params={'verb':verb}
        if args.get('resumption_token'):
            params['resumptionToken']=args['resumption_token']
        else:
            mapping={'from_date':'from','until_date':'until','set':'set','metadata_prefix':'metadataPrefix'}
            params.update({mapping[k]:v for k,v in args.items() if k in mapping})
            if verb=='ListIdentifiers':
                if not all(k in args for k in ('from_date','until_date','set')):raise ValueError('Bound ListIdentifiers by from_date, until_date and set')
                params.setdefault('metadataPrefix','cr_unixsd')
        result=request('https://oai.crossref.org/oai',params,accept='application/xml',cache=False)
        tree=ET.fromstring(result.get('text',''));ns={'o':'http://www.openarchives.org/OAI/2.0/'}
        errors=[{'code':n.get('code'),'message':n.text} for n in tree.findall('o:error',ns)]
        result.update(errors=errors,identifiers=[n.text for n in tree.findall('.//o:identifier',ns)],
            sets=[{'set':n.findtext('o:setSpec',namespaces=ns),'name':n.findtext('o:setName',namespaces=ns)} for n in tree.findall('.//o:set',ns)],
            resumption_token=tree.findtext('.//o:resumptionToken',namespaces=ns),
            reading_level='OAI public discovery metadata/identifiers only; protected GetRecord/ListRecords are not exposed')
        if any(e['code']!='noRecordsMatch' for e in errors):result['ok']=False
        return result
    raise ValueError('Unknown Crossref operation')

def spec(description,props=None,required=None):return {'description':description,'input_schema':{'type':'object','properties':props or {},'required':required or [],'additionalProperties':False}}
S={'type':'string','minLength':1};DOI={'doi':S};ARRAY={'type':'array','items':S,'minItems':1,'maxItems':20}
QUERY={'query':S,'query_fields':{'type':'object','additionalProperties':S},'filters':{'type':'array','items':S},
 'rows':{'type':'integer','minimum':0,'maximum':1000},'offset':{'type':'integer','minimum':0,'maximum':10000},
 'cursor':S,'sort':S,'order':{'type':'string','enum':['asc','desc']},'select':{'type':'array','items':S},
 'scope':{'type':'string','enum':['all','journals','members','funders','prefixes','types']},'scope_id':S,
 'facets':{'type':'object','additionalProperties':{'anyOf':[{'type':'integer','minimum':1,'maximum':100},{'type':'string','enum':['*']}]}}}
OPERATIONS={
 'service_status':spec('Проверить действующий официальный Crossref, фактический режим и ограничения; не запрашивает ключ.'),
 'works_search':spec('Поиск и фильтрация метаданных, авторов, организаций, типов, финансирования и дат; все или журнал/участник/финансирующая организация/префикс/тип. Следующая страница — cursor. Не полный текст.',QUERY),
 'work_get':spec('Полные доступные метаданные одного DOI с исходными полями и раздельными датами; abstract не равен полному тексту.',{**DOI,'refresh':{'type':'boolean'}},['doi']),
 'works_batch':spec('Последовательно проверить до 20 DOI; сохранить отдельные ошибки без подмены регистрационного агентства.',{'dois':ARRAY},['dois']),
 'bibliographic_match':spec('Найти кандидатов DOI по библиографической строке; score не является вероятностью совпадения.',{'citation':S,'expected_title':S,'rows':{'type':'integer','minimum':1,'maximum':10}},['citation']),
 'doi_agency':spec('Определить регистрационное агентство DOI, в том числе DOI вне Crossref.',DOI,['doi']),
 'doi_exists':spec('Проверить наличие DOI в Crossref через HEAD; не подтверждает научную достоверность.',DOI,['doi']),
 'work_references':spec('Прочитать ограниченную часть внесённого списка литературы и число входящих цитирований Crossref; контексты и полный мировой граф не предоставляются.',{**DOI,'start':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100}},['doi']),
 'work_relations':spec('Прочитать типизированные связи: версии, предварительные публикации, рецензии, наборы данных и другие связи, если внесены.',DOI,['doi']),
 'work_updates':spec('Проверить сообщения об исправлениях/отзыве, Crossmark и Retraction Watch; отсутствие записи не доказывает отсутствие отзыва.',{**DOI,'rows':{'type':'integer','minimum':1,'maximum':100}},['doi']),
 'work_funding':spec('Сохранить финансирование, номера грантов, идентификаторы фондов/ROR, ORCID, организации и роли авторов как внесено/дополнено.',DOI,['doi']),
 'work_licenses_links':spec('Прочитать лицензии, сроки их действия, версии и ссылки для машинного чтения; исходный текст не загружается.',DOI,['doi']),
 'entities_search':spec('Каталоги журналов, участников Crossref, фондов, типов и лицензий; результаты отражают покрытие Crossref.',{'entity':{'type':'string','enum':['journals','members','funders','types','licenses']},'query':S,'rows':{'type':'integer','minimum':0,'maximum':1000},'offset':{'type':'integer','minimum':0,'maximum':10000},'filters':{'type':'array','items':S}},['entity']),
 'entity_get':spec('Получить отдельный журнал по ISSN, участника/фонд по номеру, владельца DOI-префикса или описание типа.',{'entity':{'type':'string','enum':['journals','members','funders','prefixes','types']},'id':S},['entity','id']),
 'works_facets':spec('Получить число результатов и распределения метаданных без выгрузки всех записей; это не оценка всего научного поля.',{k:v for k,v in QUERY.items() if k not in ('rows','offset','cursor')},['facets']),
 'works_sample':spec('Получить случайную выборку метаданных Crossref до 100 записей; не воспроизводима как фиксированная выборка.',{**{k:v for k,v in QUERY.items() if k not in ('rows','offset','cursor')},'sample':{'type':'integer','minimum':1,'maximum':100}},['sample']),
 'metadata_transform':spec('Официальное преобразование одного DOI в восемь форматов и CSL-библиографию; проверять возможные потери номера статьи и дат.',{**DOI,'format':{'type':'string','enum':list(FORMATS)},'style':S,'locale':S,'output_name':S},['doi','format']),
 'citation_styles':spec('Прочитать и отфильтровать официальный каталог стилей оформления ссылок.',{'query':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':100}}),
 'export_records':spec('Сохранить метаданные до 20 DOI в JSON или CSV; раздельные даты и номер статьи сохраняются.',{'dois':ARRAY,'format':{'type':'string','enum':['json','csv']},'output_name':S},['dois','format','output_name']),
 'xml_doi_lookup':spec('Официальный XML API: метаданные одного DOI; использует согласованный технический контакт.',{**DOI,'format':{'type':'string','enum':['unixsd','unixref']}},['doi']),
 'xml_citation_match':spec('Официальное XML-сопоставление до 10 библиографических строк; сохраняет статус и кандидатов.',{'citations':{'type':'array','items':S,'minItems':1,'maxItems':10},'format':{'type':'string','enum':['unixsd','unixref']}},['citations']),
 'openurl_lookup':spec('Официальный OpenURL: метаданные по DOI либо поиск по журналу/ISSN и автору/странице, без перехода на сайт издателя.',{**DOI,**{k:S for k in ['title','issn','volume','issue','spage','aulast','date','atitle']},'format':{'type':'string','enum':['unixsd','unixref']}}),
 'data_citations':spec('Пробный официальный интерфейс 2026: связи публикаций с наборами данных Crossref/DataCite; page с 0. Не прежний Event Data и не полный граф цитирований.',{**{k:S for k in ['object_id','subject_id','from_created_date','until_created_date','relation']},'page':{'type':'integer','minimum':0},'member_id':{'type':'integer','minimum':1},'rows':{'type':'integer','minimum':1,'maximum':1000}}),
 'oai_discovery':spec('Официальный OAI-PMH: только общедоступные Identify, ListMetadataFormats, ListSets и ограниченный ListIdentifiers. Полные записи требуют иных прав.',{'verb':{'type':'string','enum':['Identify','ListMetadataFormats','ListSets','ListIdentifiers']},**{k:S for k in ['from_date','until_date','set','metadata_prefix','resumption_token']}},['verb']),
}

def call(name,args=None):
    try:
        if name not in OPERATIONS:raise ValueError('Unknown operation')
        Draft7Validator(OPERATIONS[name]['input_schema']).validate(args or {})
        return {'ok':True,'provider':'Crossref','operation':name,**execute(name,args or {})}
    except Exception as e:return {'ok':False,'provider':'Crossref','operation':name,
        'http_status':getattr(e,'status',None),'retry_after':getattr(e,'retry_after',None),'diagnostic_file':getattr(e,'diagnostic_file',None),'error':getattr(e,'message',str(e))[:800],
        'reading_level':'No successful new content reading','retry_policy':'No automatic retries or provider fallback; stop on 429 and respect retry_after'}
