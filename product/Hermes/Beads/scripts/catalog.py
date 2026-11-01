import asyncio,json
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
r=Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes')
async def main():
 async with stdio_client(StdioServerParameters(command=str(r/'bin/beads-bn-mcp'))) as streams:
  async with ClientSession(streams[0],streams[1],read_timeout_seconds=60) as c:
   init=await c.initialize();tools=await c.list_tools();d={'initialize':init.model_dump(mode='json',by_alias=True),'tools':tools.model_dump(mode='json',by_alias=True)};p=r/'Beads/config/official-mcp-catalog.json';p.write_text(json.dumps(d,ensure_ascii=False,indent=2));print([t.name for t in tools.tools])
asyncio.run(main())
