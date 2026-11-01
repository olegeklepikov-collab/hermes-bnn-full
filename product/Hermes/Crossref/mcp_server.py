import asyncio,json,uuid
from pathlib import Path
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from api import OPERATIONS,call
ROOT=Path(__file__).resolve().parent
async def list_tools(context,params):
    return types.ListToolsResult(tools=[types.Tool(name=n,description=o['description'],input_schema=o['input_schema']) for n,o in OPERATIONS.items()])
async def call_tool(context,params):
    result=await asyncio.to_thread(call,params.name,params.arguments or {})
    body=json.dumps(result,ensure_ascii=False)
    if result.get('ok') is False and len(body)>1400:
        path=ROOT/'checks'/('error-result-'+uuid.uuid4().hex+'.json');path.write_text(body);path.chmod(0o600)
        result={k:result[k] for k in ('ok','provider','operation','http_status','retry_after','partial_failure','requested','returned') if k in result}
        result.update(error='Request failed or batch partially failed; inspect the saved complete result',complete_result_file=str(path))
        body=json.dumps(result,ensure_ascii=False)
    elif len(body)>180000:
        path=ROOT/'checks'/('large-result-'+uuid.uuid4().hex+'.json');path.write_text(body);path.chmod(0o600)
        result={'ok':result.get('ok',True),'operation':params.name,'complete_result_file':str(path),
                'preview_records':result.get('records',[])[:3],'agent_preview_only':True,
                'reading_level':'Result stored; only displayed preview has been returned to the agent'}
        body=json.dumps(result,ensure_ascii=False)
    return types.CallToolResult(content=[types.TextContent(type='text',text=body)],is_error=result.get('ok') is False)
async def main():
    server=Server('Hermes BN Crossref',version='1.0.0',
        instructions='Official Crossref REST, XML, OpenURL and beta data citation APIs. No API key, authorized technical contact. Read-only metadata, not article full text. Distinguish publication/index/deposit dates, records/abstracts/full text, partial reference coverage, citation counts and context. Search score is not a match probability; missing corrections or funding means unknown, not absent. Beta dataset citations are incomplete and delayed. Do not infer licensing or access from a fulltext link. Stop on 429; transport queues requests and does not silently switch providers.',
        on_list_tools=list_tools,on_call_tool=call_tool)
    async with stdio_server() as streams:await server.run(streams[0],streams[1],server.create_initialization_options())
if __name__=='__main__':asyncio.run(main())
