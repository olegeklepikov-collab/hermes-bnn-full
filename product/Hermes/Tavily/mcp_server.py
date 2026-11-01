"""Полные актуальные схемы Tavily API для Hermes, MCP stdio, без сетевого порта."""
import asyncio
import json
import uuid
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from api import ROOT,OPERATIONS,specs,request,stream_research

TOOL_OPERATIONS={
    'tavily_search':'search',
    'tavily_extract':'extract',
    'tavily_map':'map',
    'tavily_crawl':'crawl',
    'tavily_research':'research-create',
    'tavily_get_research':'research-get',
    'tavily_research_stream':'research-stream',
    'tavily_usage':'usage',
    'tavily_logs':'logs',
}
DESCRIPTIONS={
    'tavily_search':'Полный Tavily Search: general/news/finance, четыре глубины, даты, домены, язык, точные фразы, изображения, ответы и расход.',
    'tavily_extract':'Tavily Extract: выбранные URL, basic/advanced, полный текст или отрывки, markdown/text, изображения и расход. Проверять failed_results.',
    'tavily_map':'Tavily Map: карта URL с пределом, глубиной, путями, доменами и смысловыми инструкциями; не доказывает полноту сайта.',
    'tavily_crawl':'Tavily Crawl: ограниченный корпус страниц, фильтры, basic/advanced и отрывки. Явно задавать limit и allow_external.',
    'tavily_research':'Создать исследование Tavily mini/pro/auto со схемой, четырьмя стилями ссылок, длиной и согласованными файлами. Сохранить request_id; затем получать прежнее задание через tavily_get_research.',
    'tavily_get_research':'Получить существующее исследование по request_id. completed/failed завершают ожидание; include_usage показывает расход.',
    'tavily_research_stream':'Выполнить Research с потоком SSE. Сохраняет события в собственном профиле и возвращает содержание, источники и конечный статус. Файлы передаются только по согласованному составу.',
    'tavily_usage':'Прочитать расход и предел собственного ключа/счёта. Не вызывать чаще десяти раз за десять минут.',
    'tavily_logs':'Прочитать ограниченный журнал собственного ключа. Платная возможность; filter_by_api_key:true. Не отправляет отзывы и не меняет ключи.',
}

def json_schema(value):
    if isinstance(value,list):return [json_schema(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:json_schema(v) for k,v in value.items() if k!='nullable'}
    if value.get('nullable'):return {'anyOf':[result,{'type':'null'}]}
    return result

def input_schema(operation):
    if operation=='research-get':
        return {'type':'object','properties':{'request_id':{'type':'string','description':'ID ранее созданного исследования'},'include_usage':{'type':'boolean','default':True}},'required':['request_id'],'additionalProperties':False}
    if operation=='usage':return {'type':'object','properties':{},'additionalProperties':False}
    actual='research-create' if operation=='research-stream' else operation
    method,path,index=OPERATIONS[actual];spec=specs()[index]
    schema=json_schema(spec['paths'][path][method.lower()]['requestBody']['content']['application/json']['schema'])
    schema['components']=json_schema(spec.get('components',{}))
    if operation=='research-stream':schema['properties'].pop('stream',None)
    if operation=='logs':schema['properties']['filter_by_api_key']['default']=True
    return schema

async def list_tools(context,params):
    return types.ListToolsResult(tools=[types.Tool(name=name,description=DESCRIPTIONS[name],inputSchema=input_schema(operation),annotations=types.ToolAnnotations(readOnlyHint=operation not in ['research-create','research-stream'],idempotentHint=operation not in ['research-create','research-stream'])) for name,operation in TOOL_OPERATIONS.items()])

async def call_tool(context,params):
    operation=TOOL_OPERATIONS.get(params.name);args=params.arguments or {}
    try:
        if operation is None:raise ValueError('Неизвестная операция')
        session_id=str(uuid.uuid4())
        if operation=='research-stream':
            output=ROOT/'stream-results'/(str(uuid.uuid4())+'.json')
            status,data=await asyncio.to_thread(stream_research,args,str(output),session_id)
            data={k:v for k,v in data.items() if k!='events'};data['events_file']=str(output)
        elif operation=='research-get':
            status,data=await asyncio.to_thread(request,operation,None,args['request_id'],{'include_usage':args.get('include_usage',True)},session_id)
        else:
            status,data=await asyncio.to_thread(request,operation,args if operation!='usage' else None,session_id=session_id)
        return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps({'http_status':status,'data':data},ensure_ascii=False))],isError=not (200<=status<300) or data.get('stream_completed',True) is False)
    except Exception as exc:
        return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps({'error':type(exc).__name__,'detail':'Проверьте параметры по действующей схеме, квоту и доступность Tavily.'},ensure_ascii=False))],isError=True)

async def main():
    server=Server('Hermes BN Tavily Full API',version='1.0.0',on_list_tools=list_tools,on_call_tool=call_tool)
    async with stdio_server() as (read,write):await server.run(read,write,server.create_initialization_options())

if __name__=='__main__':asyncio.run(main())
