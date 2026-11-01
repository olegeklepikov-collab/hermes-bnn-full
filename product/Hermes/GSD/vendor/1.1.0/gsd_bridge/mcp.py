"""Ограниченный MCP-сервер stdio редакции 2025-06-18.
Инструменты, ресурсы и одна инструкция. Без HTTP, сети и полномочий действия.
"""
from __future__ import annotations
import sys
from .common import ROOT, MAX_JSON_BYTES, BridgeError, canonical, read_json
from .service import Service, TOOLS
from . import __version__

PROTOCOL = '2025-06-18'
RESOURCES = {
    'gsd://integration/guide': ('Руководство по интеграции','docs/integration/GUIDE.md'),
    'gsd://integration/host-contract': ('Договор принимающей среды','docs/integration/HOST_CONTRACT.md'),
    'gsd://integration/provider': ('Договор смыслового исполнителя','docs/integration/PROVIDERS.md'),
    'gsd://gsd/guide': ('Руководство по GSD','docs/gsd/GUIDE.md'),
    'gsd://gsd/common': ('Общий договор исходного ядра','engine/COMMON.md'),
    'gsd://schema/case': ('Схема случая','engine/data/case.schema.json'),
    'gsd://schema/handoff': ('Схема передачи','engine/data/handoff.schema.json'),
    'gsd://schema/comparison': ('Схема сравнения','engine/data/comparison_review.schema.json'),
}

class MCPServer:
    def __init__(self, service=None):
        self.service = service or Service()
        self.initialized = False
        self.ready = False

    @staticmethod
    def error(request_id, code, message):
        return {'jsonrpc':'2.0','id':request_id,'error':{'code':code,'message':message}}

    def handle(self, request):
        if not isinstance(request,dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'),str):
            return self.error(None,-32600,'Некорректный запрос JSON-RPC')
        request_id=request.get('id')
        if 'id' in request and (request_id is None or type(request_id) not in (str,int)):
            return self.error(None,-32600,'Некорректный идентификатор JSON-RPC')
        method=request['method'];params=request.get('params',{})
        if not isinstance(params,dict):
            return None if 'id' not in request else self.error(request_id,-32602,'params должен быть объектом')
        if 'id' not in request:
            if method == 'notifications/initialized' and self.initialized:
                self.ready=True
            # Уведомления не требуют ответа. Отмена не прерывает текущую конечную операцию.
            return None
        try:
            if method == 'ping':
                result={}
            elif method == 'initialize':
                if self.initialized:
                    return self.error(request_id,-32600,'Повторная инициализация')
                if not isinstance(params.get('protocolVersion'),str) or not isinstance(params.get('clientInfo'),dict) or not isinstance(params.get('capabilities'),dict):
                    return self.error(request_id,-32602,'Неполный договор initialize')
                self.initialized=True
                result={'protocolVersion':PROTOCOL,'capabilities':{'tools':{},'resources':{},'prompts':{}},
                    'serverInfo':{'name':'gsd-integration','version':__version__},
                    'instructions':'Исходный GSD Engine 3.0.3. Сначала gsd_status, затем gsd_intake/gsd_context. Внешнее действие не разрешается. Пустые и частичные продукты не являются завершением.'}
            elif not self.ready:
                return self.error(request_id,-32002,'Требуются initialize и notifications/initialized')
            elif method == 'tools/list':
                if params.get('cursor'):
                    return self.error(request_id,-32602,'Курсор не поддерживается для конечного списка')
                readonly={'gsd_status','gsd_catalog','gsd_contract','gsd_context','gsd_intake','gsd_validate_case','gsd_case_get','gsd_handoff_validate','gsd_action_check','gsd_product_get','gsd_product_handoff'}
                result={'tools':[{'name':name,'description':description,'inputSchema':schema,
                    'annotations':{'readOnlyHint':name in readonly,'destructiveHint':False,
                        'idempotentHint':name in readonly,'openWorldHint':name=='gsd_execute'}}
                    for name,(description,schema) in TOOLS.items()]}
            elif method == 'tools/call':
                result_value=self.service.call(params.get('name'),params.get('arguments',{}))
                failed=not result_value['ok']
                inner=result_value.get('result',{})
                if inner.get('effective_status')=='failed' or inner.get('operation_accepted') is False:
                    failed=True
                result={'content':[{'type':'text','text':canonical(result_value).decode('utf-8')}],
                        'structuredContent':result_value,'isError':failed}
            elif method == 'resources/list':
                result={'resources':[{'uri':uri,'name':title,
                    'mimeType':'application/json' if path.endswith('.json') else 'text/markdown'}
                    for uri,(title,path) in RESOURCES.items()]}
            elif method == 'resources/read':
                uri=params.get('uri')
                if uri not in RESOURCES:
                    return self.error(request_id,-32002,'Ресурс не найден')
                _,rel=RESOURCES[uri]
                result={'contents':[{'uri':uri,'mimeType':'application/json' if rel.endswith('.json') else 'text/markdown',
                                      'text':(ROOT/rel).read_text(encoding='utf-8')}]}
            elif method == 'prompts/list':
                result={'prompts':[{'name':'gsd-workflow','description':'Последовательность содержательного применения G/S/D'}]}
            elif method == 'prompts/get':
                if params.get('name') != 'gsd-workflow':
                    return self.error(request_id,-32602,'Неизвестная инструкция')
                result={'messages':[{'role':'user','content':{'type':'text',
                    'text':(ROOT/'skills/gsd/SKILL.md').read_text(encoding='utf-8')}}]}
            else:
                return self.error(request_id,-32601,'Метод не поддерживается')
            return {'jsonrpc':'2.0','id':request_id,'result':result}
        except Exception as exc:
            return self.error(request_id,-32603,type(exc).__name__+': '+str(exc))

    def serve(self, reader=None, writer=None):
        reader=reader or sys.stdin.buffer;writer=writer or sys.stdout.buffer
        while True:
            raw=reader.readline(MAX_JSON_BYTES+1)
            if not raw:
                break
            if len(raw)>MAX_JSON_BYTES:
                response=self.error(None,-32700,'Превышен предел сообщения; соединение закрыто')
                writer.write(canonical(response)+b'\n');writer.flush();break
            try:
                request=read_json(raw)
                response=self.handle(request)
            except BridgeError as exc:
                response=self.error(None,-32700,str(exc))
            if response is not None:
                writer.write(canonical(response)+b'\n');writer.flush()
