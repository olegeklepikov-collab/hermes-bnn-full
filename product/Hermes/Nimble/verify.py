"""Проверки реальных исследовательских функций Nimble; без покупки и расписаний."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api import ROOT, request, mcp_request, private_write

DATA = ROOT / '.nimble'
CHECKS = []


def record(name, status, payload, predicate, detail=None):
    private_write(DATA / ('verify-' + name + '.json'), {'http_status': status, **payload})
    body = payload.get('response', payload)
    passed = 200 <= status < 300 and not body.get('isError') and bool(predicate(body))
    CHECKS.append({'name': name, 'passed': passed, 'http_status': status, 'details': detail or {}})
    private_write(ROOT / 'verification-summary.json', {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': CHECKS})
    print(json.dumps(CHECKS[-1], ensure_ascii=False), flush=True)
    if status == 429:
        raise SystemExit('Получен реальный предел частоты, работа остановлена.')
    return body


def http(name, op, body=None, ids=None, params=None, predicate=lambda d: bool(d), **kwargs):
    status, data = request(op, body, ids, params, **kwargs)
    return record(name, status, data, predicate)


def mcp(name, server, tool, body, predicate):
    status, data = asyncio.run(mcp_request(server, tool, body))
    return record(name, status, data, predicate)


def content_json(data):
    if data.get('structuredContent'):
        return data['structuredContent']
    for item in data.get('content', []):
        if item.get('type') == 'text':
            try:
                value = json.loads(item['text'])
            except ValueError:
                continue
            if 'conversation_id' not in value or len(value) > 1:
                return value
    return {}


def page_text(data):
    result = data.get('data', data)
    return str(result.get('markdown', result.get('content', result.get('html', ''))))


def main():
    base = {'query': 'Nimble official documentation Search and Extract API v2', 'focus': 'general',
            'include_domains': ['docs.nimbleway.com'], 'max_results': 3}
    for depth in ['lite', 'standard']:
        http('search-' + depth, 'search', {**base, 'search_depth': depth},
             predicate=lambda d: bool(d.get('results')) and len(d['results']) <= 3
             and all(urlparse(r['url']).hostname == 'docs.nimbleway.com' for r in d['results']))
    http('search-full-content', 'search', {**base, 'search_depth': 'standard', 'full_content': True, 'max_results': 2},
         predicate=lambda d: bool(d.get('results')) and any(r.get('content') for r in d['results']))
    for focus, query in [
        ('coding', 'Python asyncio TaskGroup documentation'),
        ('academic', 'Attention Is All You Need transformer research paper'),
        ('news', 'artificial intelligence latest research announcements'),
        ('location', 'public libraries in Boston Massachusetts'),
        ('shopping', 'Logitech MX Master 3S mouse'),
        ('social', 'Nimbleway official public announcements'),
        ('geo', 'Nimbleway web data platform')]:
        http('focus-' + focus, 'search', {'query': query, 'focus': focus, 'search_depth': 'lite', 'max_results': 3},
             predicate=lambda d: 'results' in d and isinstance(d['results'], list),
             )
    http('document-filter', 'search', {'query': 'Attention Is All You Need original paper', 'search_depth': 'lite',
         'focus': 'general', 'content_type': ['pdf'], 'max_results': 2},
         predicate=lambda d: bool(d.get('results')))
    http('date-and-domain-filters', 'search', {'query': 'AI research announcements', 'focus': 'news', 'search_depth': 'lite',
         'start_date': '2026-09-01', 'end_date': '2026-10-05', 'exclude_domains': ['pinterest.com'], 'country': 'US',
         'locale': 'en', 'max_results': 2}, predicate=lambda d: 'results' in d)
    http('relative-time-filter', 'search', {'query': 'AI research news', 'focus': 'news', 'search_depth': 'lite',
         'time_range': 'week', 'max_results': 2}, predicate=lambda d: 'results' in d)
    url = 'https://example.com'
    page = http('extract-static', 'extract', {'url': url, 'driver': 'vx6', 'formats': ['markdown']},
                predicate=lambda d: 'Example Domain' in page_text(d))
    parser = {'type': 'schema', 'fields': {'title': {'type': 'terminal',
        'selector': {'type': 'css', 'css_selector': 'h1'}, 'extractor': {'type': 'text'}}}}
    http('extract-parser', 'extract', {'url': url, 'driver': 'vx6', 'parse': True, 'parser': parser, 'formats': ['html']},
         predicate=lambda d: 'Example Domain' in json.dumps(d.get('data', {}).get('parsing')))
    http('extract-rendered', 'extract', {'url': url, 'driver': 'vx8', 'render': True, 'formats': ['markdown']},
         predicate=lambda d: 'Example Domain' in page_text(d))
    http('extract-xhr', 'extract', {'url': 'https://httpbin.org/json', 'is_xhr': True, 'formats': ['html']},
         predicate=lambda d: 'slideshow' in page_text(d))
    # Каталог не включает schemas; Get возвращает опубликованную версию.
    template = json.loads((DATA / 'wiki-template-schema.json').read_text())['response']
    version = template['published_version']
    from jsonschema import Draft7Validator
    params = {'article_title': 'Artificial_intelligence'}
    Draft7Validator(version['input_schema']).validate(params)
    body = {'template': template['name'], 'params': params}
    http('template-record', 'template-run', body, predicate=lambda d: bool(d.get('data', {}).get('parsing')))
    # Начать короткие задачи и сохранить идентификаторы; состояние проверяется позже.
    pending = {}
    pending['extract'] = http('extract-async-submit', 'extract-async', {'url': url, 'driver': 'vx6', 'formats': ['markdown']})
    pending['extract-batch'] = http('extract-batch-submit', 'extract-batch',
         {'inputs': [{'url': url}, {'url': 'https://docs.nimbleway.com/llms.txt'}],
          'shared_inputs': {'driver': 'vx6', 'formats': ['markdown']}})
    pending['template'] = http('template-async-submit', 'template-async', body)
    pending['template-batch'] = http('template-batch-submit', 'template-batch',
         {'shared_inputs': {'template': template['name']}, 'inputs': [{'params': params}, {'params': {'article_title': 'Machine_learning'}}]})
    finish(pending)


def finish(pending):
    base = {'query': 'Nimble official documentation Search and Extract API v2', 'focus': 'general',
            'include_domains': ['docs.nimbleway.com'], 'max_results': 3}
    url = 'https://example.com'
    http('map', 'map', {'url': 'https://docs.nimbleway.com', 'sitemap': 'only', 'domain_filter': 'domain', 'limit': 5},
         predicate=lambda d: bool(d.get('links')) and len(d['links']) <= 5)
    pending['crawl'] = http('crawl-submit', 'crawl-create',
         {'url': 'https://docs.nimbleway.com/nimble-sdk/web-search-agents/overview', 'limit': 2,
          'max_discovery_depth': 1, 'crawl_entire_domain': False, 'allow_external_links': False, 'allow_subdomains': False})
    private_write(ROOT / 'pending-tasks.json', pending)
    http('domain-driver', 'domain-driver', params={'url': 'docs.nimbleway.com'}, predicate=lambda d: bool(d.get('driver')))
    http('domain-health', 'domain-health', {'domains': ['docs.nimbleway.com']}, predicate=lambda d: bool(d))
    http('serp', 'serp', {'search_engine': 'google_search', 'query': 'site:docs.nimbleway.com Search Nimble',
         'num_results': 3, 'parse': True}, predicate=lambda d: bool(d.get('data')))
    http('serp-fast', 'serp-fast', {'search_engine': 'google_search', 'query': 'Nimble API docs', 'num_results': 3},
         predicate=lambda d: bool(d.get('data')))
    http('media-public-pdf', 'media', {'url': 'https://arxiv.org/pdf/1706.03762', 'expected_mime_types': ['application/pdf']},
         binary_output=DATA / 'test-public-document.pdf',
         predicate=lambda d: d.get('bytes', 0) > 1000 and Path(d.get('binary_output', '/nonexistent')).read_bytes().startswith(b'%PDF'))
    http('jobs-list', 'job-list', params={'limit': 3, 'offset': 0}, predicate=lambda d: isinstance(d.get('items'), list))
    mcp('mcp-search', 'nimble', 'nimble_search', {**base, 'search_depth': 'standard'},
        lambda d: bool(content_json(d).get('results')))
    mcp('mcp-extract', 'nimble', 'nimble_extract', {'url': url, 'output_format': 'markdown'},
        lambda d: 'Example Domain' in json.dumps(content_json(d)))
    mcp('mcp-answer', 'nimble', 'nimble_search', {'query': 'What is the Nimble API v2 base URL from official documentation?',
        'focus': 'general', 'search_depth': 'lite', 'include_answer': True, 'include_domains': ['docs.nimbleway.com'], 'max_results': 3},
        lambda d: bool(content_json(d).get('answer')))
    print(json.dumps({'checks': len(CHECKS), 'passed': sum(x['passed'] for x in CHECKS)}, ensure_ascii=False))


if __name__ == '__main__':
    if '--resume' in sys.argv:
        CHECKS.extend(json.loads((ROOT / 'verification-summary.json').read_text())['checks'])
        pending = {}
        for key, label in [('extract', 'extract-async-submit'), ('extract-batch', 'extract-batch-submit'), ('template', 'template-async-submit')]:
            pending[key] = json.loads((DATA / ('verify-' + label + '.json')).read_text())['response']
        template = json.loads((DATA / 'wiki-template-schema.json').read_text())['response']
        pending['template-batch'] = http('template-batch-submit', 'template-batch',
            {'shared_inputs': {'template': template['name']}, 'inputs': [{'params': {'article_title': 'Artificial_intelligence'}}, {'params': {'article_title': 'Machine_learning'}}]})
        finish(pending)
    else:
        main()
