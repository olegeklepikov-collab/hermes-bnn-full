import asyncio,json
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from api import active_operations,call
async def list_tools(context,params):
    return types.ListToolsResult(tools=[types.Tool(name=n,description=o['description'],input_schema=o['input_schema']) for n,o in active_operations().items()])
async def call_tool(context,params):
    result=await asyncio.to_thread(call,params.name,params.arguments or {})
    return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(result,ensure_ascii=False))],is_error=result.get('ok') is False)
async def main():
    server=Server('Hermes BN Web of Science preparation',version='1.0.0',instructions='Preparation only until Clarivate written AI permission, plan and separate API credentials are verified. No product data access in current mode. Do not request keys repeatedly or use unofficial MCP/browser/proxy routes to bypass licensing. Full Record is bibliographic metadata, not article full text. Public docs are instructions for developers, not retrieved scientific evidence.',on_list_tools=list_tools,on_call_tool=call_tool)
    async with stdio_server() as streams:await server.run(streams[0],streams[1],server.create_initialization_options())
if __name__=='__main__':asyncio.run(main())
