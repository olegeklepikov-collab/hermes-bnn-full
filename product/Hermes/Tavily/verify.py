"""Функциональные проверки через собственный профиль Hermes BN."""
import asyncio
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret
load_hermes_dotenv()
from api import request,private_write
ROOT=Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Tavily')
RESULTS=ROOT/'проверки';RESULTS.mkdir(exist_ok=True)

def save(label,data,seconds,status=None):
    if isinstance(data,str):
        try:data=json.loads(data)
        except ValueError:data={'text':data}
    raw=json.dumps({'elapsed_seconds':round(seconds,2),'http_status':status,'result':data},ensure_ascii=False,indent=2)
    key=get_secret('TAVILY_API_KEY')
    if key:raw=raw.replace(key,'[REDACTED]')
    private_write(RESULTS/(label+'.json'),raw)
    print(json.dumps({'test':label,'seconds':round(seconds,2),'http_status':status,'keys':list(data) if isinstance(data,dict) else None,'error':data.get('error') if isinstance(data,dict) else None},ensure_ascii=False),flush=True)

mode=sys.argv[1]
if mode=='native':
    from plugins.web.tavily.provider import TavilyWebSearchProvider
    provider=TavilyWebSearchProvider()
    start=time.monotonic();save('native-search',provider.search('Tavily official API Search documentation',2),time.monotonic()-start)
    start=time.monotonic();save('native-extract',{'results':provider.extract(['https://docs.tavily.com/documentation/api-reference/endpoint/search'])},time.monotonic()-start)
    from tavily import TavilyClient,AsyncTavilyClient
    client=TavilyClient(api_key=get_secret('TAVILY_API_KEY'),api_base_url='https://api.tavily.com')
    start=time.monotonic();save('sdk-sync',client.search('Tavily official SDK Python documentation',max_results=1,search_depth='basic',include_usage=True),time.monotonic()-start)
    async def run():
        client=AsyncTavilyClient(api_key=get_secret('TAVILY_API_KEY'),api_base_url='https://api.tavily.com')
        return await client.extract(urls=['https://httpbin.org/html'],extract_depth='basic',include_usage=True)
    start=time.monotonic();save('sdk-async',asyncio.run(run()),time.monotonic()-start)
elif mode=='api':
    jobs=json.loads(Path(sys.argv[2]).read_text())
    def run(job):
        start=time.monotonic()
        try:
            status,data=request(job['operation'],job.get('body'),job.get('id'),job.get('params'))
            save(job['label'],data,time.monotonic()-start,status)
        except Exception as exc:save(job['label'],{'error':type(exc).__name__},time.monotonic()-start)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,jobs))
else:
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_tool_discovery import register_mcp_servers
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry
    n=register_mcp_servers({'tavily':_load_mcp_config()['tavily']})
    catalog={k:registry.get_schema(k) for k in n if k.startswith('mcp__tavily__')}
    private_write(ROOT/'full-tool-catalog.json',json.dumps(catalog,ensure_ascii=False,indent=2));print('full_tools',len(catalog),flush=True)
    try:
        if mode=='catalog':print('\n'.join(catalog),flush=True)
        else:
            for job in json.loads(Path(mode).read_text()):
                name=next(k for k in catalog if k.endswith('__'+job['tool']))
                start=time.monotonic();save(job['label'],registry.dispatch(name,job['args']),time.monotonic()-start)
    finally:shutdown_mcp_servers()
