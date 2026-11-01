from pathlib import Path
import asyncio,json,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
Z=Path(__file__).resolve().parents[1];R=Z.parent;sys.path.insert(0,str(Z));from workspace_api import dump
async def main():
 async with stdio_client(StdioServerParameters(command=str(R/'bin/beads-dolt-bn-mcp'))) as streams:
  async with ClientSession(streams[0],streams[1],read_timeout_seconds=180) as c:
   init=await c.initialize();catalog=await c.list_tools();await c.send_ping();assert len(catalog.tools)==23
   outcomes=[]
   for name,args,error in [('service_status',{},False),('memory_get',{'key':'hermes-cli-check'},False),('merge_preview',{'source_branch':'bn-atomic-right','target_branch':'bn-atomic-left'},False),('export_query',{'query':"SELECT '=1+1' AS literal",'branch':'main','name':'formula-escape-check','limit':2},False),('read_documentation',{'tool':'dolt','document':'../../config/credentials.json'},True)]:
    result=await c.call_tool(name,args);assert bool(result.is_error)==error;outcomes.append({'name':name,'arguments':args,'result':result.model_dump(mode='json',by_alias=True),'expected_error':error})
   data=json.loads(outcomes[3]['result']['content'][0]['text']);assert "'=1+1" in Path(data['csv_file']).read_text();raw=json.loads(Path(data['json_file']).read_text());assert raw['rows'][0]['literal']=='=1+1'
   dump(Z/'checks/workspace-mcp-verification.json',{'initialize':init.model_dump(mode='json',by_alias=True),'catalog':catalog.model_dump(mode='json',by_alias=True),'results':outcomes,'formula_export_safety_verified':True});print('Workspace MCP catalog 23, ping, memory, atomic preview, export and errors verified')
asyncio.run(main())
