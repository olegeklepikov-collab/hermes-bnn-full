import asyncio
import threading
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool,TextContent,ListToolsResult,CallToolResult
from bn_memory import __version__
from bn_memory.schemas import SCHEMAS
from bn_memory.plugin import Host
from bn_memory.store import canonical

HOST=Host(sys.argv[1]);BROKER=HOST.broker

async def list_tools(context,params):
    return ListToolsResult(tools=[Tool(name=n,description=d,input_schema={'type':'object','properties':{**p,'_host':{'type':'object','description':'Доверенная привязка Hermes; модель не формирует.'},'_runtime':{'type':'object','description':'Конечный нативный исполнитель; заполняет только расширение Hermes.'}},'required':r,'additionalProperties':False}) for n,(d,p,r) in SCHEMAS.items() if n in HOST.rpc.tools()])

async def call_tool(context,params):
    cancel=None;cancel_var=None;cancel_token=None;nonce=None
    try:
        from hermes_constants import get_hermes_home
        if str(get_hermes_home().resolve())!=BROKER.store.namespace['profile_home']:
            raise PermissionError('native_memory_server_profile_mismatch')
        if params.name in {'document_extract','memory_compute'}:
            if params.name=='document_extract':
                from bn_memory.parser_host import CANCEL_EVENT
            else:
                from bn_memory.isolated_runtime import CANCEL_EVENT
            cancel=threading.Event();cancel_var=CANCEL_EVENT;cancel_token=cancel_var.set(cancel)
        sid,nonce=HOST.rpc.claim(params.name,dict(params.arguments))
        args={key:value for key,value in params.arguments.items() if key!='_host'}
        from bn_memory.write_origin import rpc_origin
        with rpc_origin(HOST,sid,nonce):
            value=await asyncio.to_thread(BROKER.dispatch,sid,params.name,args)
        HOST.rpc.finish(nonce,value)
        return CallToolResult(content=[TextContent(type='text',text=canonical(value))])
    except asyncio.CancelledError:
        if cancel is not None:cancel.set()
        raise
    except Exception as exc:
        value={'status':'blocked','code':type(exc).__name__+':'+str(exc)[:140]}
        if nonce is not None:HOST.rpc.finish(nonce,value,True)
        return CallToolResult(is_error=True,content=[TextContent(type='text',text=canonical(value))])

    finally:
        if cancel_token is not None:cancel_var.reset(cancel_token)

server=Server('hermes-bn-common-memory',version=__version__,on_list_tools=list_tools,on_call_tool=call_tool)
async def main():
    try:
        async with stdio_server() as (read,write):await server.run(read,write,server.create_initialization_options())
    finally:HOST.close()
if __name__=='__main__':asyncio.run(main())
