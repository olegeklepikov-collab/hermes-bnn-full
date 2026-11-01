import asyncio,json
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from api import OPERATIONS,call,status
async def list_tools(context,params):
 tools=[types.Tool(name=n,description=o['summary']+'. '+o['description'][:1200],input_schema=o['input_schema']) for n,o in OPERATIONS.items()]
 tools.append(types.Tool(name='service_status',description='Проверить собственный доступ и настройки Semantic Scholar без раскрытия ключа.',input_schema={'type':'object','properties':{},'additionalProperties':False}))
 return types.ListToolsResult(tools=tools)
async def call_tool(context,params):
 try:
  result=status() if params.name=='service_status' else await asyncio.to_thread(call,params.name,params.arguments or {})
  text=json.dumps(result,ensure_ascii=False)
  if len(text)>180000:
   from pathlib import Path
   import uuid
   p=Path(__file__).parent/'checks'/('large-result-'+uuid.uuid4().hex+'.json');p.write_text(text);p.chmod(0o600)
   data=result.get('data');preview=data[:10] if isinstance(data,list) else {**data,'data':data.get('data',[])[:10]} if isinstance(data,dict) and isinstance(data.get('data'),list) else {'stored':True}
   result={**result,'data':preview,'complete_result_file':str(p),'agent_preview_only':True};text=json.dumps(result,ensure_ascii=False)
  return types.CallToolResult(content=[types.TextContent(type='text',text=text)],is_error=result.get('ok') is False)
 except Exception as e:return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps({'ok':False,'error':str(e)},ensure_ascii=False))],is_error=True)
async def main():
 server=Server('Hermes BN Semantic Scholar',version='1.0.0',instructions='Official Semantic Scholar APIs. Metadata, AI TLDR and text snippets are different reading levels. Record sources, date, pagination and field coverage; do not infer supporting/contrasting citation stance. Datasets downloads and private data transfers require a concrete owner task.',on_list_tools=list_tools,on_call_tool=call_tool)
 async with stdio_server() as streams:await server.run(streams[0],streams[1],server.create_initialization_options())
if __name__=='__main__':asyncio.run(main())
