"""Independent Hermes BN client for the official anonymous Wolfram Cloud MCP."""
from __future__ import annotations
import asyncio, base64, json, os, re, sys
from pathlib import Path
import jsonschema

P = Path(__file__).resolve().parent
R = P.parent
MCP_URL = 'https://agenttools.wolfram.com/mcp'
TOOL_NAMES = ('WolframContext', 'WolframAlpha', 'WolframLanguageEvaluator')

def load(path):
    return json.loads(Path(path).read_text())

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    path.chmod(0o600)

def save_artifact(path, result):
    path = Path(path).resolve()
    if not path.is_relative_to((P / 'exports').resolve()):
        raise ValueError('Производные файлы сохраняются только в Wolfram/exports.')
    if result.get('isError'):
        raise ValueError('Нельзя сохранить ошибку как успешный производный файл.')
    blocks = result.get('content', [])
    images = [item for item in blocks if item.get('type') == 'image']
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if images:
        if len(images) != 1 or images[0].get('mimeType') != 'image/png' or path.suffix.lower() != '.png':
            raise ValueError('Для этого сохранения нужен один PNG и расширение .png.')
        path.write_bytes(base64.b64decode(images[0]['data'], validate=True))
    else:
        text = '\n'.join(item['text'] for item in blocks if item.get('type') == 'text')
        outputs = re.findall(r'^Out\[\d+\]=\s*(.*)', text, flags=re.M)
        if len(outputs) != 1:
            raise ValueError('Нужен один явный строковый результат ExportString.')
        value = json.loads(outputs[0])
        if not isinstance(value, str):
            raise ValueError('Результат не является строковым файлом.')
        if path.suffix.lower() == '.json':
            json.loads(value)
        elif path.suffix.lower() not in {'.csv', '.txt'}:
            raise ValueError('Выберите расширение .json, .csv или .txt.')
        path.write_text(value)
    path.chmod(0o600)
    return str(path)

def validate(name, arguments, catalog):
    if name not in TOOL_NAMES or name not in catalog:
        raise ValueError('Метод отсутствует в выбранном каталоге Wolfram.')
    jsonschema.Draft7Validator(catalog[name].input_schema).validate(arguments)
    extra = set(arguments) - set(catalog[name].input_schema['properties'])
    if extra:
        raise ValueError('Параметр не опубликован в схеме Wolfram.')
    if name == 'WolframContext' and len(arguments['context'].split()) > 250:
        raise ValueError('Описание задачи для WolframContext ограничено 250 словами.')
    if name == 'WolframLanguageEvaluator':
        seconds = arguments.get('timeConstraint', 60)
        if not 0 < seconds <= 120:
            raise ValueError('Для этого клиента выберите время от 1 до 120 секунд.')

async def request(command, name=None, arguments=None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import httpx2
    sys.path.insert(0, str(R / 'hermes-agent'))
    from tools.mcp_tool_config import _load_mcp_config
    config = _load_mcp_config().get('wolfram')
    if (not config or config.get('url') != MCP_URL or
            config.get('headers') or config.get('auth')):
        raise ValueError('Нужна отдельная анонимная конфигурация Wolfram в Hermes BN.')
    async with httpx2.AsyncClient(timeout=180) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=180) as session:
                init = await session.initialize()
                listing = await session.list_tools()
                catalog = {tool.name: tool for tool in listing.tools}
                if command == 'catalog':
                    await session.send_ping()
                    return {'initialize': init.model_dump(mode='json', by_alias=True),
                            'tools': listing.model_dump(mode='json', by_alias=True),
                            'api_key_used': False, 'ping': 'passed'}
                calls = arguments if command == 'batch' else [{'name': name, 'arguments': arguments or {}}]
                if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
                    raise ValueError('За один запуск допускается от 1 до 8 явных операций.')
                for call in calls:
                    validate(call['name'], call.get('arguments', {}), catalog)
                results = []
                for call in calls:
                    try:
                        result = await session.call_tool(call['name'], arguments=call.get('arguments', {}))
                    except Exception as error:
                        results.append({**call, 'error_type': type(error).__name__, 'error': str(error)[:2000]})
                        save(P / 'checks/last-client-failure.json', {'ok': False, 'calls': results, 'api_key_used': False})
                        raise
                    results.append({**call, 'result': result.model_dump(mode='json', by_alias=True)})
                    if result.is_error:
                        break
                    if len(calls) > 1:
                        await asyncio.sleep(1)
                if command == 'call':
                    return results[0]['result']
                return {'ok': len(results) == len(calls) and not any(x['result'].get('isError') for x in results),
                        'calls': results, 'api_key_used': False}
