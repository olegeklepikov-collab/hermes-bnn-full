"""Поиск, чтение и SELECT Keenable собственного экземпляра Hermes BN."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import requests
from jsonschema import Draft7Validator
from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret

ROOT = Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Keenable')
BASE = 'https://api.keenable.ai'
SERVERS = {'web': BASE + '/mcp', 'select': 'https://select.keenable.ai/mcp'}


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2))


def headers(public=False):
    load_hermes_dotenv()
    key = get_secret('KEENABLE_API_KEY')
    h = {'X-Keenable-Title': 'Hermes BN', 'Accept': 'application/json'}
    if not public:
        if not key:
            raise ValueError('В Hermes BN не задан KEENABLE_API_KEY')
        h['X-API-Key'] = key
    return key, h


def validate_http(operation, body):
    spec = json.loads((ROOT / 'источники/api-schema.json').read_text())
    if operation == 'search':
        schema = {**spec['components']['schemas']['SearchRequest'], 'components': spec['components'], 'additionalProperties': False}
    elif operation == 'fetch':
        fields = spec['paths']['/v1/fetch']['get']['parameters']
        schema = {'type': 'object', 'properties': {f['name']: f['schema'] for f in fields},
                  'required': [f['name'] for f in fields if f.get('required')], 'additionalProperties': False}
    else:
        schema = {'type': 'object', 'maxProperties': 0}
    Draft7Validator(schema).validate(body)
    if body.get('enableWizards') and body.get('mode', 'pro') != 'pro':
        raise ValueError('enableWizards поддерживается только с mode:pro')


def request(operation, body=None, public=False):
    body = body or {}
    if operation == 'batch-local':
        jobs = body['requests']
        if not 1 <= len(jobs) <= 50 or len({j['customId'] for j in jobs}) != len(jobs):
            raise ValueError('Нужны 1–50 запросов с уникальными customId')
        results = []
        for job in jobs:
            if job['operation'] not in ('search', 'fetch'):
                raise ValueError('Пакет поддерживает search и fetch')
            status, data = request(job['operation'], job['body'], public)
            results.append({'customId': job['customId'], 'http_status': status, 'result': data})
            if status == 429:
                break
        return 200, {'results': results, 'stopped_on_rate_limit': any(r['http_status'] == 429 for r in results),
                     'has_errors': any(r['http_status'] >= 400 for r in results), 'complete': len(results) == len(jobs)}
    if public and operation == 'identity':
        raise ValueError('identity требует ключ')
    validate_http(operation, body)
    key, h = headers(public)
    endpoint = '/v1/auth/user' if operation == 'identity' else '/v1/' + operation + ('/public' if public else '')
    with requests.Session() as s:
        if operation == 'search':
            r = s.post(BASE + endpoint, json=body, headers=h, timeout=(15, 120), allow_redirects=False)
        else:
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in body.items()}
            r = s.get(BASE + endpoint, params=params, headers=h, timeout=(15, 120), allow_redirects=False)
        try:
            data = r.json()
        except ValueError:
            data = {'error': 'Ответ сервиса не является JSON', 'http_status': r.status_code}
        if key:
            data = json.loads(json.dumps(data, ensure_ascii=False).replace(key, '[REDACTED]'))
        if r.status_code == 429:
            data['retry_after'] = r.headers.get('Retry-After')
        return r.status_code, data


async def mcp_request(server, tool, body, meta=None, public=False):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client
    import httpx2
    key, h = headers(public)
    timeout = 600 if server == 'select' else 180
    async with create_mcp_http_client(headers=h, timeout=httpx2.Timeout(timeout, connect=30)) as client:
        async with streamable_http_client(SERVERS[server], http_client=client) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=timeout) as session:
                await session.initialize()
                catalog = await session.list_tools()
                if tool == 'schema':
                    data = catalog.model_dump(mode='json', by_alias=True)
                else:
                    target = next(t for t in catalog.tools if t.name == tool)
                    Draft7Validator(target.input_schema).validate(body)
                    result = await session.call_tool(tool, body, meta=meta)
                    data = result.model_dump(mode='json', by_alias=True)
    if key:
        data = json.loads(json.dumps(data, ensure_ascii=False).replace(key, '[REDACTED]'))
    return 200, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['search', 'fetch', 'identity', 'batch-local', 'mcp', 'official-cli'])
    parser.add_argument('--input', help='Файл JSON; - означает стандартный ввод')
    parser.add_argument('--output', help='Сохранить полный ответ с правами 600')
    parser.add_argument('--public', action='store_true', help='Явно использовать доступ без ключа')
    parser.add_argument('--server', choices=list(SERVERS), default='web')
    parser.add_argument('--tool', default='schema', help='Имя инструмента MCP или schema')
    parser.add_argument('--meta', help='Файл JSON с метаданными MCP, включая keenable/overrides')
    args, cli_args = parser.parse_known_args()
    try:
        if args.operation == 'official-cli':
            if cli_args and cli_args[0] == '--':
                cli_args = cli_args[1:]
            # Официальная программа получает ключ через среду, без копии в аргументах процесса.
            # Управление ключами и чужими клиентами остаётся отдельной административной задачей.
            if not cli_args or cli_args[0] not in ('search', 'fetch', '--version', '--help'):
                raise ValueError('Оболочка поддерживает только search, fetch, --version, --help')
            key, _ = headers()
            env = dict(os.environ, KEENABLE_API_KEY=key, KEENABLE_HOME=str(ROOT / 'cli-home'))
            binary = json.loads((ROOT / 'источники/cli-installed.json').read_text())['binary']
            os.execve(binary, [binary, *cli_args], env)
        if cli_args:
            raise ValueError('Неизвестные аргументы')
        body = json.loads(sys.stdin.read() if args.input == '-' else Path(args.input).read_text()) if args.input else {}
        if args.operation == 'mcp':
            meta = json.loads(Path(args.meta).read_text()) if args.meta else None
            status, data = asyncio.run(mcp_request(args.server, args.tool, body, meta, args.public))
        else:
            status, data = request(args.operation, body, args.public)
    except Exception:
        print(json.dumps({'error': 'Проверьте параметры, ключ собственного профиля и доступность Keenable.'}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.output:
        private_write(args.output, data)
        print(json.dumps({'http_status': status, 'output': args.output, 'isError': data.get('isError', False)}, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if 200 <= status < 300 and not data.get('isError') and not data.get('error') and not data.get('has_errors') else 1


if __name__ == '__main__':
    sys.exit(main())
