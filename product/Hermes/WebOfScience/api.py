"""Own Clarivate API adapter. Product data stays gated pending written AI rights."""
from __future__ import annotations
import fcntl, json, os, re, time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote
import jsonschema, requests
from dotenv import dotenv_values

P = Path(__file__).resolve().parent
R = P.parent
TERMS = 'https://clarivate.com/wp-content/uploads/dlm_uploads/2025/05/Product-Terms-Web-of-Science-APIs-v3.8.pdf'
COMMON = ['service_status', 'capability_catalog', 'query_plan', 'access_request']

def now(): return datetime.now(timezone.utc).isoformat()
def load(path): return json.loads(path.read_text())
def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.tmp-' + os.urandom(5).hex())
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(obj, f, ensure_ascii=False, indent=2)
    temp.replace(path)

def object_schema(properties=None, required=None):
    return {'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}

DATA_OPERATIONS = load(P / 'config/operations.json')
PRODUCT_NAMES = ['starter', 'expanded', 'researcher', 'journals', 'incites']
COMMON_OPERATIONS = {
 'service_status':{'description':'Состояние подготовки Web of Science, письменного разрешения на ИИ и ключей. Не запрашивает данные Clarivate.', 'input_schema':object_schema()},
 'capability_catalog':{'description':'Официальные варианты доступа, подготовленные методы и профили. Наличие схемы не означает работающую подписку.', 'input_schema':object_schema({'product':{'type':'string','enum':PRODUCT_NAMES}})},
 'query_plan':{'description':'Местный план исследования и запросов Web of Science; API не вызывается и данные базы не читаются.', 'input_schema':object_schema({'topic':{'type':'string','minLength':1,'maxLength':1000},'purpose':{'type':'string','enum':['academic','business','general']},'year_from':{'type':'integer','minimum':1800,'maximum':2100},'year_to':{'type':'integer','minimum':1800,'maximum':2100}},['topic'])},
 'access_request':{'description':'Получить местный проект обращения в Clarivate о письменном разрешении на использование API с языковой моделью. Ничего не отправляет.', 'input_schema':object_schema()},
}
OPERATIONS = {**COMMON_OPERATIONS, **DATA_OPERATIONS}

def access_check(product, purpose='academic'):
    hold_path = P / 'config/temporary-hold.json'
    hold = load(hold_path) if hold_path.exists() else {}
    if hold.get('active'):
        return {'code':'temporary_hold','reason':hold['reason'],'state':'pending_external_decision','case_number':hold.get('case_number'),'retry_allowed':False}
    approval = load(P / 'config/access-approval.json')
    if approval.get('ai_use_authorized') is not True or approval.get('reviewed_by_owner') is not True:
        return {'code':'ai_permission_required','reason':'Пункт 4(a) текущих условий требует AI Addendum или другого письменного соглашения с Clarivate. Ключ сам по себе этого разрешения не даёт.','terms_url':TERMS}
    ref = approval.get('written_permission_document')
    if not ref or not approval.get('permission_reference'):
        return {'code':'written_agreement_not_recorded','reason':'Письменное основание доступа ещё не сохранено.'}
    path = Path(ref).resolve()
    if not path.is_relative_to(P) or not path.is_file() or not path.stat().st_size:
        return {'code':'agreement_file_missing','reason':'Нужен сохранённый документ соглашения в папке WebOfScience.'}
    expires = approval.get('expires_on')
    if expires and date.fromisoformat(expires) < date.today():
        return {'code':'permission_expired','reason':'Срок сохранённого разрешения истёк. Необходимо проверить условия продления и удаления полученных данных.'}
    if approval.get('llm_service') != 'ChatGPT' or product not in approval.get('allowed_products',[]) or purpose not in approval.get('allowed_purposes',[]):
        return {'code':'scope_not_authorized','reason':'Продукт, назначение или сервис модели не входят в сохранённое разрешение.'}
    config = load(P / 'config/products.json')[product]
    if config.get('enabled') is not True:
        return {'code':'product_not_enabled','reason':'План продукта ещё не подключён и не проверен.'}
    return None

def credential(product):
    # Only this instance's dedicated file; no ambient/other-instance credentials.
    config = load(P / 'config/products.json')[product]
    values = dotenv_values(P / 'config/credentials.env') if (P / 'config/credentials.env').is_file() else {}
    return values.get(config['key_name'])

def active_operations():
    result = dict(COMMON_OPERATIONS)
    # On first setup all product methods remain absent from the agent catalog.
    for name, op in DATA_OPERATIONS.items():
        try:allowed = any(access_check(op['product'], p) is None for p in ['academic','business','general'])
        except Exception:allowed = False
        if allowed and credential(op['product']): result[name] = op
    return result

def request_shape(name, arguments):
    op = DATA_OPERATIONS[name]
    jsonschema.validate(arguments, op['input_schema'])
    a = {**op['defaults'], **arguments}; a.pop('purpose', None)
    spans = [k for k in ['publishTimeSpan','loadTimeSpan','createdTimeSpan','modifiedTimeSpan','tcModifiedTimeSpan'] if a.get(k)]
    if len(spans)>1: raise ValueError('Временные параметры несовместимы; выберите один согласно документации.')
    db = a.get('db', a.get('databaseId'))
    if db=='WOK' and any(a.get(k) for k in ['modifiedTimeSpan','tcModifiedTimeSpan']):
        raise ValueError('Обновления записей не поддерживаются для WOK.')
    if a.get('viewField') and a.get('optionView')=='SR':
        raise ValueError('Выбор полей требует optionView=FS; задайте это явно.')
    if a.get('optionView')=='FS' and not a.get('viewField'):
        raise ValueError('Для FS нужен viewField.')
    if name=='starter_search' and a.get('page',1)*a.get('limit',3)>100000:
        raise ValueError('Запрошенная страница выходит за документированный предел Starter 100000 записей.')
    path = op['path']
    for key in op['fields']['path']:
        if key not in a: raise ValueError('Не задан обязательный параметр пути.')
        path = path.replace('{'+key+'}', quote(str(a[key]),safe=''))
    if '{' in path or '}' in path: raise ValueError('Неразрешённый шаблон пути.')
    query = {key:a[key] for key in op['fields']['query'] if key in a}
    for key,value in list(query.items()):
        if isinstance(value,bool):query[key]='true' if value else 'false'
        if isinstance(value,list):query[key]=','.join(str(x) for x in value)
    body = {key:a[key] for key in op['fields']['body'] if key in a} or None
    return op['method'], op['base_url'].rstrip('/') + path, query, body

def send_data_request(name, args):
    op = DATA_OPERATIONS[name];product=op['product'];purpose=args.get('purpose','academic')
    denied = access_check(product,purpose)
    if denied: return {'ok':False,'product':product,'blocked':denied,'network_request_performed':False,'api_data_read':False}
    key = credential(product)
    if not key: return {'ok':False,'product':product,'blocked':{'code':'api_key_missing','reason':'Отдельный ключ Hermes BN ещё не сохранён.'},'network_request_performed':False,'api_data_read':False}
    method,url,query,body = request_shape(name,args)
    config = load(P / 'config/products.json')[product]
    cap = int(config['records_per_request_cap'])
    for keyname in ['limit','count','recordcount']:
        value = (body or {}).get(keyname,query.get(keyname))
        if value is not None and value>cap:
            return {'ok':False,'blocked':{'code':'local_record_cap','reason':f'Местный предел — {cap} записей. Увеличение требует проверки плана.'},'network_request_performed':False}
    lock=P/'data'/('quota-'+product+'.json')
    with open(lock,'a+') as f:
        os.chmod(lock,0o600);fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        value=f.read();state=json.loads(value) if value else {};day=datetime.now(timezone.utc).date().isoformat()
        used=state.get('attempted_requests',0) if state.get('utc_day')==day else 0
        if used>=int(config['daily_request_cap']):
            return {'ok':False,'blocked':{'code':'local_daily_cap','reason':'Местный суточный предел достигнут; сброс по UTC не гарантирует сброс квоты сервиса.'},'network_request_performed':False}
        time.sleep(max(0,float(config['request_interval_seconds'])-(time.time()-state.get('last_request_time',0))))
        state={'utc_day':day,'attempted_requests':used+1,'last_request_time':time.time()}
        f.seek(0);f.truncate();json.dump(state,f);f.flush()
        response=requests.request(method,url,params=query,json=body,headers={'X-ApiKey':key,'Accept':'application/json','User-Agent':'HermesBN-WebOfScience/1.0'},timeout=(15,90),allow_redirects=False)
    # Error bodies can repeat requests/credentials; retain only status and safe guidance.
    if response.status_code!=200:
        return {'ok':False,'product':product,'http_status':response.status_code,'network_request_performed':True,'api_data_read':False,
                'retry_after':response.headers.get('Retry-After'),'error':'API вернул отказ. Ключ, права, параметры и квота проверяются отдельно; повтор и подмена службы не выполняются.'}
    data=response.json();text=json.dumps(data,ensure_ascii=False)
    data=json.loads(text.replace(key,'[REDACTED]'))
    result={'ok':True,'product':product,'provider':'Clarivate '+product+' API','api_endpoint':url,'http_status':200,
            'parameters':query if method=='GET' else body,'retrieved_at':now(),'data':data,'api_data_read':True,
            'network_request_performed':True,'reading_level':'API metadata, metrics or citation links only; not article full text',
            'full_article_read':False,'attribution':'© '+str(date.today().year)+' Clarivate',
            'usage_notice':'Certain data included herein are derived from the © Web of Science ('+date.today().isoformat()+') of Clarivate. All rights reserved. You may not copy or re-distribute this material in whole or in part without the prior written consent of Clarivate.',
            'citation_scope':'Counts and graph coverage refer to the licensed selected database and retrieval date, not all scholarly citations.',
            'local_attempted_requests_today':used+1}
    if len(text)>90000:
        output=P/'data'/('licensed-result-'+os.urandom(8).hex()+'.json');save(output,result)
        result.pop('data');result.update({'complete_result_file':str(output),'agent_preview_only':True,'reading_level':'Result metadata and saved-file location only; read authorized saved data separately.'})
    return result

def call(name, args):
    try:
        if name not in OPERATIONS: raise ValueError('Неизвестная операция.')
        if name in COMMON_OPERATIONS:jsonschema.validate(args,COMMON_OPERATIONS[name]['input_schema'])
        # Data calls are gated BEFORE schema evaluation or credential access.
        result=send_data_request(name,dict(args)) if name in DATA_OPERATIONS else common_call(name,args)
        result.setdefault('ok',True);result['tool']=name;result['checked_at']=now();return result
    except ValueError as e:return {'ok':False,'tool':name,'error':str(e)}
    except Exception as e:return {'ok':False,'tool':name,'error_type':type(e).__name__,'error':'Операция не выполнена; секреты и содержание ответа при ошибке не выводятся.'}

def common_call(name,a):
    products=load(P/'config/products.json')
    if name=='service_status':
        approval=load(P/'config/access-approval.json')
        outbound=load(P/'config/outbound-request.json') if (P/'config/outbound-request.json').exists() else {'sent':False}
        return {'mode':'prepared_pending_written_ai_permission_and_api_credentials','data_access_enabled':bool(set(active_operations())-set(COMMON)),
                'temporary_hold':load(P/'config/temporary-hold.json') if (P/'config/temporary-hold.json').exists() else {'active':False},
                'ai_use_authorized':approval.get('ai_use_authorized') is True,'live_api_verified':False,
                'products':{k:{'configured_plan':v['configured_plan'],'enabled':v['enabled'],'key_present':bool(credential(k)),'access_block':access_check(k)} for k,v in products.items()},
                'prepared_api_methods':len(DATA_OPERATIONS),'prepared_profiles':len(load(P/'config/profiles.json')),'active_mcp_tools':len(active_operations()),
                'terms':{'url':TERMS,'section':'4(a)','version':'3.8','document_last_updated':'2024-07-17','currently_linked_by_portal':True},
                'pending':['written_AI_permission_from_Clarivate','appropriate_plan','separate_API_key','live_functional_tests'],
                'permission_request_sent':outbound.get('sent',False),'case_number':outbound.get('case_number'),
                'verification':load(P/'config/verification.json')}
    if name=='capability_catalog':
        names=[a['product']] if a.get('product') else PRODUCT_NAMES
        return {'products':{k:{'documentation':products[k]['documentation'],'base_url':products[k]['base_url'],'enabled':products[k]['enabled'],
                             'methods':[{ 'name':n,'method':op['method'],'path':op['path']} for n,op in DATA_OPERATIONS.items() if op['product']==k]} for k in names},
                'other_options':{'official_web_interface':'https://www.webofscience.com/','bulk_XML':'Separate license and delivery agreement; not enabled.',
                                 'Research_Assistant_and_Research_Intelligence':'Native Clarivate AI products; not proof of permission for Hermes or an open API.',
                                 'Reviewer_Locator':'Separate editorial/grant workflow subscription; contacts and invitations not part of this setup.',
                                 'SUSHI':'Library usage statistics, not scientific evidence discovery; not enabled.',
                                 'Lite_and_SOAP':'Legacy/replaced; not selected.',
                                 'official_public_MCP':'Not found in reviewed public official materials; ask Clarivate.'},
                'profiles':{k:v for k,v in load(P/'config/profiles.json').items() if DATA_OPERATIONS[v['name']]['product'] in names},
                'network_request_performed':False,'api_data_read':False}
    if name=='query_plan':
        topic=a['topic'].strip()
        if not topic:raise ValueError('Тема пуста.')
        purpose=a.get('purpose','academic');query='TS=('+topic+')'
        if 'year_from' in a or 'year_to' in a:
            first=a.get('year_from',1900);last=a.get('year_to',date.today().year)
            if first>last:raise ValueError('Начальный год больше конечного.')
            query+=' AND PY=('+str(first)+'-'+str(last)+')'
        return {'purpose':purpose,'starter_query':query,'expanded_query':query,'review_query':query+' AND DT=(Review)',
                'stages':['Starter: обнаружение и основные сведения','Expanded: аннотации, связи цитирования, организации и финансирование','Researcher: идентификация исследователей и доступные сведения','Journals: показатели журнала с явным годом','InCites: нормированные показатели с датой версии'],
                'date_rule':'PY включает итоговый год и ранний доступ; Starter может не возвращать дату раннего доступа. При необходимости используется FPY и проверяются даты записи.',
                'metrics_rule':'Число цитирований и показатели журнала не являются оценкой достоверности отдельного исследования.',
                'coverage':'Доступ определяется коллекцией, изданием, периодом и договором; Full Record означает метаданные, не текст публикации.',
                'execution_allowed':False,'network_request_performed':False,'api_data_read':False,'requires':'Written AI Addendum/agreement before API use with Hermes.'}
    if name=='access_request':
        p=P/'обращения/Clarivate — разрешение для Hermes BN.txt'
        outbound=load(P/'config/outbound-request.json') if (P/'config/outbound-request.json').exists() else {'sent':False}
        return {'draft_file':str(p),'draft':p.read_text(),'contact_url':'https://developer.clarivate.com/content/contact',
                'support_url':'https://supportcenter.clarivate.com/s/submit-a-case','this_tool_sends_nothing':True,
                'outbound_request':outbound,'avoid_duplicate_request':outbound.get('sent',False)}
    raise ValueError('Неизвестная служебная операция.')
