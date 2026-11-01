import asyncio,json
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
z=Path(__file__).resolve().parents[1]
async def main():
 async with stdio_client(StdioServerParameters(command=str(z.parent/'bin/dolt-bn-official-mcp'))) as streams:
  async with ClientSession(streams[0],streams[1],read_timeout_seconds=60) as c:
   init=await c.initialize();tools=await c.list_tools();d={'initialize':init.model_dump(mode='json',by_alias=True),'tools':tools.model_dump(mode='json',by_alias=True)};p=z/'config/official-mcp-catalog.json';p.write_text(json.dumps(d,ensure_ascii=False,indent=2));print([t.name for t in tools.tools])
asyncio.run(main())
