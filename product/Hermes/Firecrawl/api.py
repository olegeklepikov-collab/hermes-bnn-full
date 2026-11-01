"""Прямой API для расширенных форматов и операций вне схемы MCP."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from hermes_cli.env_loader import load_hermes_dotenv

OPERATIONS = {
    'scrape': ('POST', '/scrape'),
    'batch-scrape': ('POST', '/batch/scrape'),
    'batch-status': ('GET', '/batch/scrape/{id}'),
    'browser-create': ('POST', '/interact'),
    'browser-execute': ('POST', '/interact/{id}/execute'),
    'browser-stop': ('DELETE', '/interact/{id}'),
    'monitor-create': ('POST', '/monitor'),
    'monitor-update': ('PATCH', '/monitor/{id}'),
    'monitor-get': ('GET', '/monitor/{id}'),
}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=OPERATIONS)
    parser.add_argument('--id')
    parser.add_argument('--input',help='Файл JSON; "-" означает стандартный ввод')
    parser.add_argument('--output',help='Сохранить ответ в файл с правами 600')
    args=parser.parse_args()
    method,path=OPERATIONS[args.operation]
    if '{id}' in path:
        if not args.id or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',args.id):
            parser.error('Требуется корректный идентификатор задания')
        path=path.format(id=args.id)
    payload=None
    if args.input:
        payload=json.loads(sys.stdin.read() if args.input=='-' else Path(args.input).read_text())
        if not isinstance(payload,dict):parser.error('Тело запроса должно быть объектом JSON')
    load_hermes_dotenv()
    key=os.getenv('FIRECRAWL_API_KEY')
    if not key:
        parser.error('В профиле Hermes BN отсутствует FIRECRAWL_API_KEY')
    response=requests.request(method,'https://api.firecrawl.dev/v2'+path,
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
        json=payload,timeout=180,allow_redirects=False)
    try: data=response.json()
    except ValueError: data={'success':False,'http_status':response.status_code,'error':'Ответ не содержит JSON'}
    rendered=json.dumps(data,ensure_ascii=False,indent=2)
    rendered=re.sub(r'fc-[A-Za-z0-9_-]{20,}','[REDACTED]',rendered)
    if args.output:
        output=Path(args.output)
        output.write_text(rendered)
        output.chmod(0o600)
        print(json.dumps({'http_status':response.status_code,'output':str(output),'success':data.get('success')},ensure_ascii=False))
    else: print(rendered)
    return 0 if response.ok and data.get('success',True) else 1

if __name__=='__main__': sys.exit(main())
