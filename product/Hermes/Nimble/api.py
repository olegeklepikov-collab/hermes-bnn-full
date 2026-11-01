"""Полный программный доступ Nimble в собственном профиле Hermes BN."""
import argparse
import asyncio
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests
from jsonschema import Draft202012Validator, FormatChecker
from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret

ROOT = Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes/Nimble')
DATA = ROOT / '.nimble'
BASE = 'https://sdk.nimbleway.com'
MCP = {'nimble': 'https://mcp.nimbleway.com/mcp', 'docs': 'https://docs.nimbleway.com/mcp'}
OPERATIONS = {
    'search': ('POST', '/v2/search'),
    'extract': ('POST', '/v2/extract'),
    'extract-async': ('POST', '/v2/extract/async'),
    'extract-batch': ('POST', '/v2/extract/batch'),
    'map': ('POST', '/v2/map'),
    'crawl-create': ('POST', '/v2/crawl'),
    'crawl-list': ('GET', '/v2/crawl'),
    'crawl-get': ('GET', '/v2/crawl/{id}'),
    'crawl-cancel': ('DELETE', '/v2/crawl/{id}'),
    'template-list': ('GET', '/v2/extract/templates'),
    'template-get': ('GET', '/v2/extract/templates/{extract_template_name}'),
    'template-run': ('POST', '/v2/extract/templates/run'),
    'template-async': ('POST', '/v2/extract/templates/async'),
    'template-batch': ('POST', '/v2/extract/templates/batch'),
    'template-generate': ('POST', '/v2/extract/templates/generations'),
    'template-generation-get': ('GET', '/v2/extract/templates/generations/{generation_id}'),
    'template-versions': ('GET', '/v2/extract/templates/{extract_template_name}/versions'),
    'template-version-get': ('GET', '/v2/extract/templates/{extract_template_name}/versions/{version_id}'),
    'agent-list': ('GET', '/v2/agents'),
    'agent-create': ('POST', '/v2/agents'),
    'agent-get': ('GET', '/v2/agents/{agent_id}'),
    'agent-update': ('PATCH', '/v2/agents/{agent_id}'),
    'agent-deactivate': ('DELETE', '/v2/agents/{agent_id}'),
    'agent-template-list': ('GET', '/v2/agents/templates'),
    'agent-template-get': ('GET', '/v2/agents/templates/{template_name}'),
    'agent-run': ('POST', '/v2/agents/runs'),
    'agent-run-start': ('POST', '/v2/agents/{agent_id}/runs'),
    'agent-run-list': ('GET', '/v2/agents/{agent_id}/runs'),
    'agent-run-get': ('GET', '/v2/agents/{agent_id}/runs/{run_id}'),
    'agent-run-result': ('GET', '/v2/agents/{agent_id}/runs/{run_id}/result'),
    'agent-events': ('GET', '/v2/agents/{agent_id}/runs/{run_id}/events'),
    'task-list': ('GET', '/v2/tasks'),
    'task-get': ('GET', '/v2/tasks/{task_id}'),
    'task-results': ('GET', '/v2/tasks/{task_id}/results'),
    'batch-list': ('GET', '/v2/batches'),
    'batch-get': ('GET', '/v2/batches/{batch_id}'),
    'batch-progress': ('GET', '/v2/batches/{batch_id}/progress'),
    'domain-driver': ('GET', '/v2/domain-knowledge/driver'),
    'domain-health': ('POST', '/v1/domain-health/check'),
    'serp': ('POST', '/v2/serp'),
    'serp-fast': ('POST', '/v1/realtime/serp'),
    'serp-async': ('POST', '/v2/serp/async'),
    'serp-batch': ('POST', '/v2/serp/batch'),
    'media': ('POST', '/v2/media'),
    'media-async': ('POST', '/v2/media/async'),
    'job-list': ('GET', '/v2/jobs'),
    'job-create': ('POST', '/v2/jobs'),
    'job-get': ('GET', '/v2/jobs/{job_id}'),
    'job-update': ('PATCH', '/v2/jobs/{job_id}'),
    'job-delete': ('DELETE', '/v2/jobs/{job_id}'),
    'job-run-start': ('POST', '/v2/jobs/{job_id}/runs'),
    'job-run-list': ('GET', '/v2/jobs/{job_id}/runs'),
    'job-run-get': ('GET', '/v2/jobs/runs/{run_id}'),
    'job-run-cancel': ('POST', '/v2/jobs/runs/{run_id}/cancel'),
    'job-artifacts': ('GET', '/v2/jobs/runs/{run_id}/artifacts'),
    'job-artifact-get': ('GET', '/v2/jobs/runs/{run_id}/artifacts/{artifact_id}'),
    'job-artifact-preview': ('GET', '/v2/jobs/runs/{run_id}/artifacts/{artifact_id}/preview'),
    'job-artifact-download-url': ('GET', '/v2/jobs/runs/{run_id}/artifacts/{artifact_id}/download-url'),
}


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))


@lru_cache(maxsize=1)
def spec():
    return json.loads((ROOT / 'источники/openapi.json').read_text())


def credentials():
    load_hermes_dotenv()
    key = get_secret('NIMBLE_API_KEY')
    if not key:
        raise ValueError('В собственном профиле Hermes BN не задан NIMBLE_API_KEY')
    return key, {'Authorization': 'Bearer ' + key, 'X-Client-Source': 'hermes'}


def schema_fields(schema, seen=None):
    seen = set() if seen is None else seen
    if '$ref' in schema:
        ref = schema['$ref']
        if ref in seen:
            return set()
        seen.add(ref)
        schema = spec()['components']['schemas'][ref.rsplit('/', 1)[1]]
    out = set(schema.get('properties', {}))
    for field in ['allOf', 'anyOf', 'oneOf']:
        for child in schema.get(field, []):
            out |= schema_fields(child, seen.copy())
    return out


def validate(operation, body, ids, params):
    method, path = OPERATIONS[operation]
    endpoint = spec()['paths'][path][method.lower()]
    shape = endpoint.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
    if shape:
        Draft202012Validator({**shape, 'components': spec()['components']}, format_checker=FormatChecker()).validate(body)
        known = schema_fields(shape)
        if known and isinstance(body, dict) and set(body) - known:
            raise ValueError('Неизвестные поля запроса')
    elif body not in (None, {}):
        raise ValueError('Операция не принимает тело')
    for location, values in [('path', ids), ('query', params)]:
        fields = [v for v in endpoint.get('parameters', []) if v['in'] == location]
        # API выдаёт идентификаторы wsa_.../task_run_..., хотя OpenAPI помечает
        # некоторые параметры пути как uuid. Тип и состав параметров проверяются;
        # этот устаревший формат не отбрасывает идентификаторы самого сервиса.
        shapes = {v['name']: {k: value for k, value in v['schema'].items()
                             if not (location == 'path' and k == 'format' and value == 'uuid')} for v in fields}
        rules = {'type': 'object', 'properties': shapes,
                 'required': [v['name'] for v in fields if v.get('required')], 'additionalProperties': False}
        Draft202012Validator(rules, format_checker=FormatChecker()).validate(values)
    if operation == 'search':
        if params:
            raise ValueError('Search принимает параметры в JSON')
        if body.get('time_range') and (body.get('start_date') or body.get('end_date')):
            raise ValueError('Нельзя совмещать time_range с датами')
        if body.get('content_type') and body.get('focus', 'general') != 'general':
            raise ValueError('content_type требует focus:general')


def request(operation, body=None, ids=None, params=None, binary_output=None):
    ids, params = ids or {}, params or {}
    validate(operation, body, ids, params)
    key, headers = credentials()
    method, path = OPERATIONS[operation]
    for name, value in ids.items():
        path = path.replace('{' + name + '}', quote(str(value), safe=''))
    with requests.Session() as session:
        response = session.request(method, BASE + path, headers=headers, params=params,
            json=body if body is not None else None, timeout=(20, 300), allow_redirects=False)
        content_type = response.headers.get('Content-Type', '')
        if binary_output and response.ok and 'json' not in content_type:
            f = Path(binary_output)
            f.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(f, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(response.content)
            data = {'binary_output': str(f), 'bytes': len(response.content), 'content_type': content_type}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {'content_type': content_type, 'text': response.text[:20000]}
        data = json.loads(json.dumps(data, ensure_ascii=False).replace(key, '[REDACTED]'))
        rate_headers = {k: v for k, v in response.headers.items() if k.lower().startswith(('ratelimit-', 'x-ratelimit-')) or k.lower() == 'retry-after'}
        return response.status_code, {'response': data, 'rate_headers': rate_headers}


async def mcp_request(server, tool, body):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client
    import httpx2
    key, headers = credentials() if server == 'nimble' else (None, {})
    async with create_mcp_http_client(headers=headers, timeout=httpx2.Timeout(300, connect=30)) as client:
        async with streamable_http_client(MCP[server], http_client=client) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=300) as session:
                await session.initialize()
                catalog = await session.list_tools()
                if tool == 'schema':
                    data = catalog.model_dump(mode='json', by_alias=True)
                else:
                    target = next(t for t in catalog.tools if t.name == tool)
                    properties = target.input_schema.get('properties', {})
                    if 'context' in properties:
                        body = dict(body)
                        body.setdefault('context', 'Retrieving and organizing publicly available web information to support cited business, academic, and general research with verifiable sources and structured outputs.')
                    state_file = DATA / 'mcp-conversation.json'
                    if 'conversation_id' in properties and state_file.exists():
                        body.setdefault('conversation_id', json.loads(state_file.read_text())['conversation_id'])
                    Draft202012Validator(target.input_schema).validate(body)
                    result = await session.call_tool(tool, body)
                    data = result.model_dump(mode='json', by_alias=True)
                    for content in data.get('content', []):
                        if content.get('type') != 'text':
                            continue
                        try:
                            value = json.loads(content['text'])
                        except ValueError:
                            continue
                        cid = value.get('conversation_id') or value.get('_mcp_instructions', {}).get('conversation_id')
                        if cid:
                            private_write(state_file, {'conversation_id': cid})
    if key:
        data = json.loads(json.dumps(data, ensure_ascii=False).replace(key, '[REDACTED]'))
    return 200, data


def stream_events(ids, params, output, max_events=50):
    validate('agent-events', None, ids, params)
    key, headers = credentials()
    path = OPERATIONS['agent-events'][1]
    for name, value in ids.items():
        path = path.replace('{' + name + '}', quote(str(value), safe=''))
    events, lines, event_type, done = [], [], '', False
    with requests.get(BASE + path, headers={**headers, 'Accept': 'text/event-stream'}, params=params,
                      timeout=(20, 90), stream=True, allow_redirects=False) as response:
        if not response.ok:
            return response.status_code, {'error': 'Поток не открыт', 'http_status': response.status_code}
        for line in response.iter_lines(decode_unicode=True):
            if isinstance(line, bytes):
                line = line.decode('utf-8')
            if line.startswith('event:'):
                event_type = line[6:].strip()
            elif line.startswith('data:'):
                lines.append(line[5:].lstrip())
            elif not line and lines:
                text = '\n'.join(lines).replace(key, '[REDACTED]')
                try:
                    data = json.loads(text)
                except ValueError:
                    data = {'text': text}
                events.append({'event': event_type, 'data': data})
                private_write(output, {'events': events, 'stream_completed': False})
                done = bool(re.search(r'"status"\s*:\s*"(?:completed|failed|cancelled)"', text))
                if done or len(events) >= max_events:
                    break
                lines, event_type = [], ''
        data = {'events': events, 'stream_completed': done, 'limit_reached': len(events) >= max_events}
        private_write(output, data)
        return response.status_code, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=[*OPERATIONS, 'mcp', 'cli'])
    parser.add_argument('--input', help='Файл JSON; - означает стандартный ввод')
    parser.add_argument('--ids', help='Файл JSON с идентификаторами в пути')
    parser.add_argument('--params', help='Файл JSON с параметрами GET')
    parser.add_argument('--output', help='Сохранить ответ с правами 600')
    parser.add_argument('--binary-output', help='Сохранить исходный двоичный документ')
    parser.add_argument('--server', choices=list(MCP), default='nimble')
    parser.add_argument('--tool', default='schema')
    parser.add_argument('--max-events', type=int, default=50)
    args, cli_args = parser.parse_known_args()
    try:
        if args.operation == 'cli':
            if cli_args and cli_args[0] == '--':
                cli_args = cli_args[1:]
            blocked = ['--api-key', '--debug', '--base-url']
            if not cli_args or cli_args[0] in ('login', 'logout', 'whoami') or any(
                token == option or token.startswith(option + '=') for token in cli_args for option in blocked):
                raise ValueError('Ключ берётся из собственного профиля; вход и отладка выполняются отдельно')
            key, _ = credentials()
            env = dict(os.environ, NIMBLE_API_KEY=key, CLIENT_SOURCE='hermes')
            cli = ROOT / 'runtime/node_modules/.bin/nimble'
            os.execve(str(cli), [str(cli), '--base-url', BASE, '--format', 'json', *cli_args], env)
        if cli_args:
            raise ValueError('Неизвестные аргументы')
        body = json.loads(sys.stdin.read() if args.input == '-' else Path(args.input).read_text()) if args.input else None
        ids = json.loads(Path(args.ids).read_text()) if args.ids else {}
        params = json.loads(Path(args.params).read_text()) if args.params else {}
        if args.operation == 'mcp':
            status, data = asyncio.run(mcp_request(args.server, args.tool, body or {}))
        elif args.operation == 'agent-events':
            if not args.output:
                parser.error('Для событий требуется --output')
            status, data = stream_events(ids, params, args.output, args.max_events)
        else:
            status, data = request(args.operation, body, ids, params, args.binary_output)
    except Exception as exc:
        key = get_secret('NIMBLE_API_KEY') or ''
        detail = str(exc).replace(key, '[REDACTED]') if key else str(exc)
        print(json.dumps({'error': type(exc).__name__, 'detail': detail[:800]}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.output:
        private_write(args.output, data)
        print(json.dumps({'http_status': status, 'output': args.output, 'isError': data.get('isError', False)}, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if 200 <= status < 300 and not data.get('isError') else 1


if __name__ == '__main__':
    sys.exit(main())
