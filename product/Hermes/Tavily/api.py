"""Полный исследовательский Tavily API собственного профиля Hermes BN."""
import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

import requests
from jsonschema import Draft7Validator,FormatChecker
from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret

ROOT=Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Tavily')
OPERATIONS={
    'search':('POST','/search','2'),
    'extract':('POST','/extract','3'),
    'crawl':('POST','/crawl','4'),
    'map':('POST','/map','5'),
    'research-create':('POST','/research','6'),
    'research-get':('GET','/research/{request_id}','7'),
    'usage':('GET','/usage','9'),
    'logs':('POST','/logs','10'),
}

@lru_cache(maxsize=1)
def specs():return json.loads((ROOT/'источники/api-schemas.json').read_text())

def private_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600);os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as f:f.write(text)

def credentials(session_id=None,project_id=None):
    load_hermes_dotenv();key=get_secret('TAVILY_API_KEY')
    if not key:raise ValueError('В собственном профиле отсутствует TAVILY_API_KEY')
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','X-Client-Name':'Hermes BN'}
    if session_id:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',session_id):raise ValueError('Некорректный session_id')
        headers['X-Session-Id']=session_id
    if project_id:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',project_id):raise ValueError('Некорректный project_id')
        headers['X-Project-ID']=project_id
    return key,headers

def validate(operation,body):
    method,path,index=OPERATIONS[operation];spec=specs()[index]
    schema=spec['paths'][path][method.lower()].get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
    if schema:Draft7Validator({**schema,'components':spec.get('components',{})},format_checker=FormatChecker()).validate(body)

def request(operation,body=None,request_id=None,params=None,session_id=None,project_id=None):
    if operation=='batch-local':
        jobs=body['requests'];ids=[v['customId'] for v in jobs]
        if len(ids)!=len(set(ids)):raise ValueError('Нужны уникальные customId')
        if any(v['operation'] not in ['search','extract','map','crawl'] for v in jobs):raise ValueError('Research создаётся и отслеживается отдельно')
        def run(job):
            status,data=request(job['operation'],job['body'],session_id=session_id,project_id=project_id)
            return {'customId':job['customId'],'http_status':status,'result':data}
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,jobs))
        return 200,{'mode':'local','items':results,'has_errors':any(v['http_status']>=400 for v in results)}
    method,path,index=OPERATIONS[operation]
    if isinstance(body,dict):
        required=specs()[index]['paths'][path][method.lower()].get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema',{}).get('required',[])
        body={k:v for k,v in body.items() if v is not None or k in required}
    if '{request_id}' in path:
        if not request_id or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',request_id):raise ValueError('Некорректный идентификатор исследования')
        path=path.format(request_id=request_id)
    if operation=='logs':body={**(body or {})};body.setdefault('filter_by_api_key',True)
    validate(operation,body)
    if operation=='research-create' and body.get('stream'):raise ValueError('Для потока выберите research-stream')
    key,headers=credentials(session_id,project_id)
    response=requests.request(method,'https://api.tavily.com'+path,headers=headers,json=body,params=params,timeout=(15,210),allow_redirects=False)
    try:data=response.json()
    except ValueError:data={'error':'Ответ не содержит JSON','http_status':response.status_code}
    data=json.loads(json.dumps(data,ensure_ascii=False).replace(key,'[REDACTED]'))
    return response.status_code,data

def stream_research(body,output,session_id=None,project_id=None):
    body={**body,'stream':True};validate('research-create',body)
    key,headers=credentials(session_id,project_id);headers['Accept']='text/event-stream'
    events=[];text=[];structured=None;sources=[];done=False;event_name=None;parts=[]
    with requests.post('https://api.tavily.com/research',json=body,headers=headers,stream=True,timeout=(15,240),allow_redirects=False) as response:
        if not response.ok:
            try:data=response.json()
            except ValueError:data={'error':'Поток не открыт'}
            private_write(output,json.dumps(data,ensure_ascii=False).replace(key,'[REDACTED]'))
            return response.status_code,data
        task_id=response.headers.get('x-request-id')
        def consume():
            nonlocal done,structured,sources
            if event_name=='done':done=True
            raw='\n'.join(parts)
            if raw.strip()=='[DONE]':done=True;return
            if not raw:return
            try:data=json.loads(raw)
            except ValueError:events.append({'event':event_name,'text':raw});return
            events.append(data)
            for choice in data.get('choices',[]):
                delta=choice.get('delta',{});content=delta.get('content')
                if isinstance(content,str):text.append(content)
                elif isinstance(content,dict):structured=content if structured is None else {**structured,**content}
                if delta.get('sources'):sources=delta['sources']
            if len(events)==1 or len(events)%20==0:
                private_write(output,json.dumps({'stream_completed':done,'request_id':task_id,'stream_id':events[0].get('id'),'content':structured if structured is not None else ''.join(text),'sources':sources,'events':events},ensure_ascii=False,indent=2).replace(key,'[REDACTED]'))
        for line in response.iter_lines(decode_unicode=True):
            if isinstance(line,bytes):line=line.decode('utf-8')
            if line=='':consume();parts=[];event_name=None
            elif line.startswith('event:'):event_name=line[6:].strip()
            elif line.startswith('data:'):parts.append(line[5:].lstrip())
        if parts or event_name:consume()
        data={'stream_completed':done,'request_id':task_id,'stream_id':events[0].get('id') if events and isinstance(events[0],dict) else None,'content':structured if structured is not None else ''.join(text),'sources':sources,'events':events}
        private_write(output,json.dumps(data,ensure_ascii=False,indent=2).replace(key,'[REDACTED]'))
        return response.status_code,data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=[*OPERATIONS,'batch-local','research-stream'])
    parser.add_argument('--input',help='Файл JSON; - означает стандартный ввод')
    parser.add_argument('--id',help='request_id исследования')
    parser.add_argument('--params',help='Файл JSON с параметрами GET')
    parser.add_argument('--output',help='Сохранить ответ с правами 600')
    parser.add_argument('--session-id',help='Неперсональный идентификатор одной задачи')
    parser.add_argument('--project-id',help='Уже существующий идентификатор проекта Tavily')
    args=parser.parse_args()
    if args.operation=='research-stream' and not args.output:parser.error('Для сохранения потока требуется --output')
    session_id=args.session_id or str(uuid.uuid4())
    try:
        body=json.loads(sys.stdin.read() if args.input=='-' else Path(args.input).read_text()) if args.input else None
        params=json.loads(Path(args.params).read_text()) if args.params else None
        if args.operation=='research-stream':status,data=stream_research(body,args.output,session_id,args.project_id)
        else:status,data=request(args.operation,body,args.id,params,session_id,args.project_id)
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'detail':'Проверьте параметры по сохранённой официальной схеме, ключ профиля и доступность сервиса.'},ensure_ascii=False),file=sys.stderr);return 2
    if args.output:
        if args.operation!='research-stream':private_write(args.output,json.dumps(data,ensure_ascii=False,indent=2))
        print(json.dumps({'http_status':status,'request_id':data.get('request_id'),'status':data.get('status'),'stream_completed':data.get('stream_completed'),'usage':data.get('usage'),'output':args.output},ensure_ascii=False))
    else:print(json.dumps(data,ensure_ascii=False,indent=2))
    return 0 if 200<=status<300 and not data.get('has_errors') and data.get('stream_completed',True) else 1

if __name__=='__main__':sys.exit(main())
