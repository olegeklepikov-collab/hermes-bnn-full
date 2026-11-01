import asyncio,json
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from api import OPERATIONS,call
async def list_tools(context,params):
 tools=[types.Tool(name=n,description=o['description'],input_schema=o['input_schema']) for n,o in OPERATIONS.items()]
 
 return types.ListToolsResult(tools=tools)
async def call_tool(context,params):
 try:
  result=await asyncio.to_thread(call,params.name,params.arguments or {})
  text=json.dumps(result,ensure_ascii=False)
  if len(text)>180000:
   from pathlib import Path
   import uuid
   p=Path(__file__).parent/'checks'/('large-result-'+uuid.uuid4().hex+'.json');p.write_text(text);p.chmod(0o600)
   result={'ok':result.get('ok',True),'tool':params.name,'complete_result_file':str(p),'agent_preview_only':True,'preview_records':result.get('records',[])[:5],'reading_level':'preview; read complete result file for the full response'};text=json.dumps(result,ensure_ascii=False)
  return types.CallToolResult(content=[types.TextContent(type='text',text=text)],is_error=result.get('ok') is False)
 except Exception as e:return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps({'ok':False,'error':str(e)},ensure_ascii=False))],is_error=True)
async def main():
 server=Server('Hermes BN PubMed and PMC',version='1.0.0',instructions='PubMed records contain metadata and abstracts, not full articles. PMC Cloud tools read licensed article versions and specified sections/tables. Distinguish reading levels, record query translation, pagination, corrections and source coverage. No clinical recommendations without appropriate source evaluation. NCBI policies: https://www.ncbi.nlm.nih.gov/home/about/policies/.',on_list_tools=list_tools,on_call_tool=call_tool)
 async with stdio_server() as streams:await server.run(streams[0],streams[1],server.create_initialization_options())
if __name__=='__main__':asyncio.run(main())
