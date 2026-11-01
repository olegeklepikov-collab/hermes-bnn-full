"""Проверка через действующий профиль и обработчики инструментов Hermes BN."""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()
ROOT = Path(os.environ['HERMES_BN_ROOT']) / 'Firecrawl'
RESULTS = ROOT / 'проверки'
RESULTS.mkdir(exist_ok=True)

def redact(text):
    return re.sub(r'fc-[A-Za-z0-9_-]{20,}', '[REDACTED]', text)

def save(label, raw, elapsed):
    raw = redact(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))
    try:
        data = json.loads(raw)
    except ValueError:
        data = {'text': raw}
    (RESULTS / (label + '.json')).write_text(json.dumps({'elapsed_seconds': round(elapsed, 2), 'result': data}, ensure_ascii=False, indent=2))
    print(json.dumps({'test': label, 'seconds': round(elapsed, 2), 'result': data}, ensure_ascii=False)[:4000], flush=True)

if sys.argv[1] == 'native':
    from tools.web_tools import web_search_tool, web_extract_tool, _get_search_backend, _get_extract_backend
    print('backends', _get_search_backend(), _get_extract_backend(), flush=True)
    start=time.monotonic()
    save('native-search', web_search_tool('site:docs.firecrawl.dev MCP Firecrawl', limit=2), time.monotonic()-start)
    start=time.monotonic()
    save('native-extract', asyncio.run(web_extract_tool(['https://example.com'], char_limit=3000)), time.monotonic()-start)
else:
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_tool_discovery import register_mcp_servers
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry
    names = register_mcp_servers(_load_mcp_config())
    catalog = {n: registry.get_schema(n) for n in names if 'firecrawl' in n}
    (ROOT/'tool-catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    print('registered',len(catalog), flush=True)
    try:
        if sys.argv[1] == 'catalog':
            print('\n'.join(catalog), flush=True)
        elif sys.argv[1] == 'monitor':
            def call(tool,args,label):
                name=next(n for n in catalog if n.endswith(tool))
                start=time.monotonic()
                raw=registry.dispatch(name,args)
                save(label,raw,time.monotonic()-start)
                data=json.loads(raw) if isinstance(raw,str) else raw
                return json.loads(data['result']) if isinstance(data.get('result'),str) else data
            created=call('firecrawl_monitor_create',{'body':{'name':'Hermes BN — проверка подключения (пауза)','schedule':{'text':'weekly','timezone':'UTC'},'targets':[{'type':'scrape','urls':['https://httpbin.org/html']}],'judgeEnabled':False,'retentionDays':1}},'monitor-created')
            if created.get('success'):
                mid=created['data']['id']
                paused=call('firecrawl_monitor_update',{'id':mid,'body':{'status':'paused'}},'monitor-paused')
                assert paused.get('success') and paused['data']['status']=='paused', 'Не удалось подтвердить паузу тестового наблюдения'
                call('firecrawl_monitor_get',{'id':mid},'monitor-get')
                call('firecrawl_monitor_run',{'id':mid},'monitor-run-once')
            else:
                raise RuntimeError('Не удалось создать тестовое наблюдение')
        else:
            jobs = json.loads(Path(sys.argv[1]).read_text())
            for job in jobs:
                n=next(n for n in catalog if n.endswith(job['tool']))
                start=time.monotonic()
                save(job['label'],registry.dispatch(n,job['args']),time.monotonic()-start)
    finally:
        shutdown_mcp_servers()
