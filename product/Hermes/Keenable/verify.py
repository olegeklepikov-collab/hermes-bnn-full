"""Проверки реального доступа Keenable; ответы сохраняются отдельно от отчёта."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api import ROOT, request, mcp_request, private_write

EVIDENCE = ROOT / 'verification'
EVIDENCE.mkdir(exist_ok=True)
checks = []


def record(name, status, data, predicate, details=None):
    private_write(EVIDENCE / (name + '.json'), {'http_status': status, 'response': data})
    ok = 200 <= status < 300 and not data.get('isError') and not data.get('error') and predicate(data)
    checks.append({'name': name, 'passed': bool(ok), 'http_status': status, 'details': details or {}})
    private_write(ROOT / 'verification-summary.json', {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks})
    print(json.dumps(checks[-1], ensure_ascii=False), flush=True)
    if status == 429 or (data.get('isError') and re.search(r'\b429\b|rate.?limit', json.dumps(data), re.I)):
        raise SystemExit('Получен реальный предел частоты; проверка остановлена.')
    return data


def http(name, operation, body, predicate, public=False, details=None):
    status, data = request(operation, body, public)
    return record(name, status, data, predicate, details)


def mcp(name, server, tool, body, predicate, meta=None, details=None):
    status, data = asyncio.run(mcp_request(server, tool, body, meta))
    return record(name, status, data, predicate, details)


def json_content(data):
    return json.loads(next(c['text'] for c in data['content'] if c['type'] == 'text'))


def results_ok(data):
    return bool(data.get('results')) and len(data['results']) <= 3 and all(
        urlparse(r['url']).hostname == 'docs.keenable.ai' and len(r.get('snippet', '')) <= 2000 for r in data['results'])


def timestamps_within(data, field, start, end):
    values = [r.get(field) for r in data.get('results', [])]
    return bool(values) and all(v and start <= datetime.fromisoformat(v.replace('Z', '+00:00')) <= end for v in values)


def main():
    ex = ROOT / 'examples'
    base = json.loads((ex / 'search.json').read_text())
    http('identity', 'identity', {}, lambda d: d.get('org_id') == '3ea0c2d2-73a3-45f6-93cf-b4975e7967ee')
    for mode in ['pro', 'realtime']:
        http('search-' + mode, 'search', {**base, 'mode': mode}, lambda d, m=mode: d.get('mode') == m and results_ok(d))
    # Даты проверяются по возвращённым значениям, а не только по отсутствию ошибки.
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
    dated = {**base, 'published_after': '2026-08-01', 'published_before': '2026-08-31'}
    http('published-window', 'search', dated, lambda d: timestamps_within(d, 'published_at', start, end))
    acquired_start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    acquired_end = datetime(2026, 9, 30, 23, 59, 59, 999000, tzinfo=timezone.utc)
    http('acquired-window', 'search', {**base, 'acquired_after': '2026-09-01', 'acquired_before': '2026-09-30'},
         lambda d: timestamps_within(d, 'acquired_at', acquired_start, acquired_end))
    reference = datetime(2026, 10, 1, tzinfo=timezone.utc)
    historical = {**base, 'query_time': '2026-10-01T00:00:00Z', 'acquired_after': '30d', 'acquired_before': '2026-09-30',
                  'published_after': '1y', 'published_before': '2026-09-30'}
    http('historical-relative-window', 'search', historical,
         lambda d: timestamps_within(d, 'acquired_at', acquired_start, reference)
         and timestamps_within(d, 'published_at', datetime(2025, 10, 1, tzinfo=timezone.utc), reference))
    http('public-search', 'search', {**base, 'mode': 'realtime'}, results_ok, public=True)
    http('experimental-wizards', 'search', {'query': 'Current Apple Inc AAPL share price market capitalization financial quote',
         'mode': 'pro', 'max_results': 3, 'enableWizards': True}, lambda d: d.get('mode') == 'pro' and bool(d.get('results')),
         details={'experimental': True, 'wizard_match_not_guaranteed': True})
    url = 'https://docs.keenable.ai/credits'
    pages = []
    for live in [False, True]:
        pages.append(http('fetch-' + ('live' if live else 'indexed'), 'fetch', {'url': url, 'live': live, 'max_chars': 15000},
          lambda d: '100,000' in d.get('content', '') and len(d.get('content', '')) <= 15000))
    http('fetch-targeted', 'fetch', {'url': url, 'max_chars': 5000,
         'prompt': 'Return only the number of free API requests per monthly cycle for an authenticated organization; integer only.'},
         lambda d: '100000' in re.sub(r'[,\s]', '', d.get('content', '')))
    http('public-fetch', 'fetch', {'url': url, 'max_chars': 15000}, lambda d: '100,000' in d.get('content', ''), public=True)
    http('batch-local', 'batch-local', json.loads((ex / 'batch.json').read_text()),
         lambda d: d.get('complete') and not d.get('has_errors') and len(d['results']) == 2)
    search = json.loads((ex / 'mcp-search.json').read_text())
    mcp('mcp-search-json', 'web', 'search_web_pages', search,
        lambda d: results_ok(json_content(d)) and d.get('_meta', {}).get('keenable/usage', {}).get('sku') == 'search.pro')
    mcp('mcp-operator-override', 'web', 'search_web_pages', search,
        lambda d: json_content(d).get('mode') == 'realtime' and d.get('_meta', {}).get('keenable/usage', {}).get('sku') == 'search.realtime',
        meta=json.loads((ex / 'overrides.json').read_text()))
    fetch = json.loads((ex / 'mcp-fetch.json').read_text())
    mcp('mcp-fetch-json', 'web', 'fetch_page_content', fetch,
        lambda d: '100,000' in json_content(d).get('content', '') and d.get('_meta', {}).get('keenable/usage', {}).get('sku') == 'fetch')
    mcp('mcp-fetch-live-text', 'web', 'fetch_page_content', {**fetch, 'live': True, 'output_format': 'text'},
        lambda d: any('100,000' in c.get('text', '') for c in d['content']) and d.get('_meta', {}).get('keenable/usage', {}).get('sku') == 'fetch.live')
    # Таблица уже получена при подготовке: используем именно эти наборы, не повторяя извлечение.
    original = json.loads((ROOT / 'check-select.json').read_text())
    table = original['_meta']['webql_result']
    record('select-evidence', 200, original,
        lambda d: len(table['rows']) == 2 and any(r.get('monthly_requests') == 100000 for r in table['rows'])
        and any(r.get('organization_rps') == 10 for r in table['rows'])
        and all(r.get('monthly_requests_evidence') for r in table['rows']))
    rid = table['result_set_id']
    fetch_id = re.search(r'Fetch result set: (r[a-z0-9]+)', json.dumps(table['notes']))[1]
    aggregate = f"SELECT COUNT(DISTINCT url) AS sources,\n  MAX(TRY_CAST(monthly_requests AS INTEGER)) AS monthly_requests,\n  MAX(TRY_CAST(organization_rps AS INTEGER)) AS organization_rps\nFROM {rid}"
    mcp('select-reuse-aggregate', 'select', 'select', {'query': aggregate},
        lambda d: d['_meta']['webql_result']['rows'][0] == {'sources': 2, 'monthly_requests': 100000, 'organization_rps': 10})
    semantics = f"SELECT url,\n  SEM_NORM(title, 'keep monthly allowance and rate limit topics distinct') AS topic,\n  SEM_MATCH(content, 'states per-second API rate limits by authentication status') AS has_rate_table,\n  SEM_SCORE(content, 'authenticated organization requests-per-second limits') AS relevance,\n  UNNEST(SEM_EXTRACT_ALL(content,\n    'authentication category explicitly listed in the rate-limit table',\n    authentication := 'authentication category name as stated in the table',\n    rps := 'requests per second for that category; number only, NULL when absent',\n    hourly := 'requests per hour for that category; number only, NULL when absent',\n    evidence := 'per_field'\n  ), recursive := true)\nFROM {fetch_id}\nWHERE url = 'https://docs.keenable.ai/rate-limits'"
    mcp('select-semantic-functions', 'select', 'select', {'query': semantics},
        lambda d: len(d['_meta']['webql_result']['rows']) >= 2 and all(r['has_rate_table'] is True and isinstance(r['relevance'], (int, float)) for r in d['_meta']['webql_result']['rows']))
    mcp('select-preview', 'select', 'select', {'query': f'SELECT url, monthly_requests\nFROM {rid}\nORDER BY url', 'show_preview': True},
        lambda d: d['_meta']['webql_result']['total_rows'] == 2)
    queries = [
        'site:docs.keenable.ai how API keys authorize clients',
        'site:docs.keenable.ai search historical index query time',
        'site:docs.keenable.ai live fetch extraction prompt',
        'site:docs.keenable.ai organization request rate limits',
        'site:docs.keenable.ai monthly credits free allowance',
        'site:docs.keenable.ai SELECT result sets semantic functions']
    sql = 'SELECT url, title, published_at\nFROM WEB_SEARCH(\n  ' + ',\n  '.join("'" + q + "'" for q in queries) + "\n)\nWHERE starts_with(url, 'https://docs.keenable.ai/')\nORDER BY url\nLIMIT 3"
    mcp('select-web-search', 'select', 'select', {'query': sql},
        lambda d: bool(d['_meta']['webql_result']['rows']) and all(r['url'].startswith('https://docs.keenable.ai/') for r in d['_meta']['webql_result']['rows']))
    # Цитаты SELECT сверяются с полученным полным текстом источника.
    for row in table['rows']:
        _, page = request('fetch', {'url': row['url'], 'max_chars': 20000})
        normalize = lambda v: re.sub(r'\s+', ' ', v).strip()
        quotes = [q for key, value in row.items() if key.endswith('_evidence') and value for q in value]
        record('evidence-' + row['url'].rsplit('/', 1)[1], 200, page,
            lambda d, qq=quotes: all(normalize(q) in normalize(d['content']) for q in qq))
    print(json.dumps({'total': len(checks), 'passed': sum(c['passed'] for c in checks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
