"""Прямой Exa API собственного профиля Hermes BN; ключ не передаётся в URL."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
import yaml
from jsonschema import Draft202012Validator,FormatChecker
from concurrent.futures import ThreadPoolExecutor
from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret

ROOT = Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Exa')
OPERATIONS = {
    'search': ('POST', '/search'),
    'contents': ('POST', '/contents'),
    'answer': ('POST', '/answer'),
    'agent-create': ('POST', '/agent/runs'),
    'agent-get': ('GET', '/agent/runs/{id}'),
    'agent-list': ('GET', '/agent/runs'),
    'agent-events': ('GET', '/agent/runs/{id}/events'),
    'agent-cancel': ('POST', '/agent/runs/{id}/cancel'),
    'agent-stop': ('POST', '/agent/runs/{id}/stop'),
    'batch-create': ('POST', '/batches'),
    'batch-get': ('GET', '/batches/{id}'),
    'batch-list': ('GET', '/batches'),
    'batch-cancel': ('POST', '/batches/{id}/cancel'),
    'monitor-list': ('GET', '/monitors'),
    'monitor-create': ('POST', '/monitors'),
    'monitor-get': ('GET', '/monitors/{id}'),
    'monitor-update': ('PATCH', '/monitors/{id}'),
    'monitor-trigger': ('POST', '/monitors/{id}/trigger'),
    'monitor-runs': ('GET', '/monitors/{id}/runs'),
    'monitor-run-get': ('GET', '/monitors/{id}/runs/{runId}'),
    'websets-team': ('GET', '/v0/teams/me'),
    'websets-list': ('GET', '/v0/websets'),
    'websets-preview': ('POST', '/v0/websets/preview'),
    'websets-get': ('GET', '/v0/websets/{id}'),
    'websets-items': ('GET', '/v0/websets/{id}/items'),
}

def private_write(path, text):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as f:f.write(text)

def request(operation,payload=None,identifier=None,run_id=None,params=None):
    if operation=='batch-local':
        spec=yaml.safe_load((ROOT/'источники/exa-spec.yaml').read_text())
        Draft202012Validator({'$ref':'#/components/schemas/CreateBatchRequest','components':spec['components']},format_checker=FormatChecker()).validate(payload)
        ids=[v['customId'] for v in payload['requests']]
        if len(ids)!=len(set(ids)):raise ValueError('В пакете нужны уникальные customId')
        def run(item):
            name={'/search':'search','/agent/runs':'agent-create'}[item['url']]
            status,data=request(name,item['body'])
            return {'customId':item['customId'],'http_status':status,'status':data.get('status','completed' if status==200 else 'failed'),'result':data}
        with ThreadPoolExecutor(max_workers=2) as pool:items=list(pool.map(run,payload['requests']))
        return 200,{'mode':'local','items':items,'has_errors':any(v['http_status']>=400 for v in items)}
    method,template=OPERATIONS[operation]
    for name,value in [('id',identifier),('runId',run_id)]:
        if '{'+name+'}' in template and not (value and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value)):
            raise ValueError('Требуется корректный идентификатор задания')
    path=template.format(id=identifier,runId=run_id)
    spec=yaml.safe_load((ROOT/'источники/exa-spec.yaml').read_text())
    schema=spec['paths'][template][method.lower()].get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
    if schema:
        Draft202012Validator({**schema,'components':spec['components']},format_checker=FormatChecker()).validate(payload)
    if isinstance(payload,dict) and payload.get('stream'):
        raise ValueError('Эта команда принимает конечный JSON. Для потока используйте официальный SDK.')
    load_hermes_dotenv()
    key=get_secret('EXA_API_KEY')
    if not key:raise ValueError('В профиле Hermes BN отсутствует EXA_API_KEY')
    response=requests.request(method,'https://api.exa.ai'+path,
        headers={'x-api-key':key,'Content-Type':'application/json'},json=payload,
        params=params,timeout=180,allow_redirects=False)
    try:data=response.json()
    except ValueError:data={'error':'Ответ не содержит JSON','http_status':response.status_code}
    safe=json.loads(json.dumps(data,ensure_ascii=False).replace(key,'[REDACTED]'))
    return response.status_code,safe

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=[*OPERATIONS,'batch-local'])
    parser.add_argument('--id')
    parser.add_argument('--run-id')
    parser.add_argument('--input',help='Файл JSON; "-" означает стандартный ввод')
    parser.add_argument('--params',help='Файл JSON с параметрами GET')
    parser.add_argument('--output',help='Файл ответа с правами 600')
    args=parser.parse_args()
    if args.operation=='monitor-create' and not args.output:
        parser.error('Для одноразового секрета уведомлений требуется --output: ответ будет сохранён с правами 600')
    try:
        payload=json.loads(sys.stdin.read() if args.input=='-' else Path(args.input).read_text()) if args.input else None
        params=json.loads(Path(args.params).read_text()) if args.params else None
        status,data=request(args.operation,payload,args.id,args.run_id,params)
    except Exception as exc:
        # Не печатать тело запроса, заголовки или значение ключа при ошибке схемы.
        print(json.dumps({'error':type(exc).__name__,'detail':'Проверьте ключ профиля, тело запроса и доступность сервиса.'},ensure_ascii=False),file=sys.stderr)
        return 2
    rendered=json.dumps(data,ensure_ascii=False,indent=2)
    if args.output:
        private_write(args.output,rendered)
        print(json.dumps({'http_status':status,'requestId':data.get('requestId'),'costDollars':data.get('costDollars'),'output':args.output},ensure_ascii=False))
    else:print(rendered)
    return 0 if 200<=status<300 and not data.get('has_errors') else 1

if __name__=='__main__':sys.exit(main())
