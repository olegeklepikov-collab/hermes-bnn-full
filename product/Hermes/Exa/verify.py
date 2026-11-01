"""Проверки действующего профиля и обработчиков Hermes BN."""
import asyncio
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret
load_hermes_dotenv()
ROOT=Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Exa')
RESULTS=ROOT/'проверки'
RESULTS.mkdir(exist_ok=True)
from api import request,private_write

def save(label,result,seconds,status=None):
    key=get_secret('EXA_API_KEY')
    if isinstance(result,str):
        try:result=json.loads(result)
        except ValueError:result={'text':result}
    raw=json.dumps({'elapsed_seconds':round(seconds,2),'http_status':status,'result':result},ensure_ascii=False,indent=2)
    if key:raw=raw.replace(key,'[REDACTED]')
    private_write(RESULTS/(label+'.json'),raw)
    print(json.dumps({'test':label,'seconds':round(seconds,2),'http_status':status,'keys':list(result) if isinstance(result,dict) else None,'error':result.get('error') if isinstance(result,dict) else None},ensure_ascii=False),flush=True)

mode=sys.argv[1]
if mode=='native':
    from tools.web_tools import web_search_tool,web_extract_tool,_get_search_backend,_get_extract_backend
    print('backends',_get_search_backend(),_get_extract_backend(),flush=True)
    start=time.monotonic();save('native-search',web_search_tool('Official Exa documentation for search and page contents',2),time.monotonic()-start)
    start=time.monotonic();save('native-firecrawl-extract',asyncio.run(web_extract_tool(['https://httpbin.org/html'],char_limit=3000)),time.monotonic()-start)
    from plugins.web.exa.provider import ExaWebSearchProvider
    start=time.monotonic();save('native-exa-extract',{'results':ExaWebSearchProvider().extract(['https://exa.ai/docs/contents/quickstart'])},time.monotonic()-start)
elif mode=='api':
    jobs=json.loads(Path(sys.argv[2]).read_text())
    def run(job):
        start=time.monotonic()
        try:
            status,data=request(job['operation'],job.get('body'),job.get('id'),job.get('run_id'),job.get('params'))
            save(job['label'],data,time.monotonic()-start,status)
        except Exception as exc:save(job['label'],{'error':type(exc).__name__},time.monotonic()-start)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,jobs))
else:
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_tool_discovery import register_mcp_servers
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry
    config=_load_mcp_config()
    names=register_mcp_servers({'exa':config['exa']})
    catalog={n:registry.get_schema(n) for n in names if n.startswith('mcp__exa__')}
    private_write(ROOT/'tool-catalog.json',json.dumps(catalog,ensure_ascii=False,indent=2))
    print('registered',len(catalog),flush=True)
    try:
        if mode=='catalog':print('\n'.join(catalog),flush=True)
        else:
            for job in json.loads(Path(mode).read_text()):
                name=next(n for n in catalog if n.endswith('__'+job['tool']))
                start=time.monotonic();save(job['label'],registry.dispatch(name,job['args']),time.monotonic()-start)
    finally:shutdown_mcp_servers()
