"""Assisted research: external discovery and local, owner-supplied documents.

This adapter never requests publication pages from the three target sites.
"""
from __future__ import annotations
import fcntl, hashlib, importlib.util, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
import requests

P = Path(__file__).resolve().parent
R = P.parent
sys.path.insert(0, str(P / 'deps'))
sys.path.insert(0, str(R / 'hermes-agent'))
from pypdf import PdfReader

def now():
    return datetime.now(timezone.utc).isoformat()

def load_json(path):
    return json.loads(path.read_text())

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.tmp-' + os.urandom(5).hex())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def paced_request(fn):
    path = P / 'data' / 'request.lock'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'a+') as f:
        os.chmod(path, 0o600)
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        previous = float(f.read() or 0)
        time.sleep(max(0, 1.1 - (time.time() - previous)))
        f.seek(0); f.truncate(); f.write(str(time.time())); f.flush()
        return fn()

def platform(name):
    sources = load_json(P / 'config' / 'sources.json')
    if name not in sources:
        raise ValueError('Неизвестная площадка: выберите elibrary, dissercat или cyberleninka.')
    return sources[name]

def valid_url(value):
    p = urlsplit(value)
    if p.scheme not in {'https', 'http'} or not p.hostname or p.username or p.password:
        raise ValueError('Нужен адрес http/https без учётных данных.')
    return value

def schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}

STRING = {'type': 'string'}
PLATFORM = {'type': 'string', 'enum': ['elibrary', 'dissercat', 'cyberleninka']}
ID = {'type': 'string', 'pattern': '^doc-[a-f0-9]{24}$'}
KINDS = ['article', 'dissertation', 'abstract_of_dissertation', 'bibliography', 'other', 'test_fixture']
OPERATIONS = {
    'service_status': {'description': 'Состояние режимов и ограничения трёх площадок. Не обращается к их сайтам.', 'input_schema': schema()},
    'source_options': {'description': 'Возможности площадки, официальные инструкции и основания доступа.', 'input_schema': schema({'platform': PLATFORM}, ['platform'])},
    'query_plan': {'description': 'План поиска: внешние запросы и отдельные действия в официальном интерфейсе.', 'input_schema': schema({'platform': PLATFORM, 'topic': STRING, 'purpose': {'type': 'string', 'enum': ['business', 'academic', 'general']}, 'year_from': {'type': 'integer', 'minimum': 1800, 'maximum': 2100}}, ['platform', 'topic'])},
    'search_candidates': {'description': 'Внешний поиск через Tavily Search по домену площадки. Только отрывки указателя; оригинал не читается.', 'input_schema': schema({'platform': PLATFORM, 'query': STRING, 'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 8}, 'time_range': {'type': 'string', 'enum': ['day', 'week', 'month', 'year']}}, ['platform', 'query'])},
    'resolve_doi': {'description': 'Проверка DOI по официальным метаданным Crossref; не чтение статьи или целевой площадки.', 'input_schema': schema({'doi': STRING}, ['doi'])},
    'import_document': {'description': 'Добавить законно полученный местный PDF/TXT/MD/CSV/RIS/BibTeX из папки inbox. Файл этим инструментом не скачивается и не загружается в облако. Выбранные впоследствии отрывки возвращаются модели Hermes. Основание использования указывает владелец.', 'input_schema': schema({'path': STRING, 'platform': PLATFORM, 'source_url': STRING, 'title': STRING, 'document_kind': {'type': 'string', 'enum': KINDS}, 'rights_confirmed': {'type': 'boolean', 'const': True}, 'rights_basis': STRING, 'license': STRING, 'year': {'type': 'integer'}, 'authors': {'type': 'array', 'items': STRING}}, ['path', 'platform', 'source_url', 'title', 'document_kind', 'rights_confirmed', 'rights_basis'])},
    'document_info': {'description': 'Местные сведения о документе, происхождение, контрольная сумма, объём извлечения. Сам текст не читается.', 'input_schema': schema({'document_id': ID}, ['document_id'])},
    'read_pages': {'description': 'Прочитать извлечённый текст выбранных физических страниц местного документа. Изображения, таблицы и весь документ этим не проверяются.', 'input_schema': schema({'document_id': ID, 'pages': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}, 'minItems': 1, 'maxItems': 6}, 'max_chars_per_page': {'type': 'integer', 'minimum': 100, 'maximum': 12000}, 'offset': {'type': 'integer', 'minimum': 0}}, ['document_id', 'pages'])},
    'find_in_document': {'description': 'Найти буквальную фразу в извлечённом местном тексте с контекстами и страницами. Это поиск внутри полученного файла, не корпуса площадки.', 'input_schema': schema({'document_id': ID, 'query': STRING, 'max_hits': {'type': 'integer', 'minimum': 1, 'maximum': 30}, 'case_sensitive': {'type': 'boolean'}}, ['document_id', 'query'])},
    'export_document_metadata': {'description': 'Сохранить местную карточку с происхождением в JSON или RIS. Сведения владельца не превращаются в проверенную библиографию.', 'input_schema': schema({'document_id': ID, 'format': {'type': 'string', 'enum': ['json', 'ris']}}, ['document_id'])},
    'permission_request': {'description': 'Подготовить текст обращения о разрешении на доступ и применении в бизнесе; сохраняет местный файл, ничего не отправляет.', 'input_schema': schema({'platform': PLATFORM}, ['platform'])},
}

def classify_url(url, name):
    p = urlsplit(url).path.lower()
    if name == 'elibrary':
        return 'publication_card_candidate' if p.endswith('/item.asp') else 'catalog_or_other_page'
    if name == 'dissercat':
        return 'dissertation_or_abstract_card_candidate' if p.startswith('/content/') else 'catalog_or_other_page'
    if '/article/n/' in p:
        return 'pdf_link_candidate' if p.endswith(('/pdf', '.pdf')) else 'article_card_candidate'
    return 'catalog_or_other_page'

def validate_args(name, args):
    import jsonschema
    if name not in OPERATIONS:
        raise ValueError('Неизвестный инструмент.')
    jsonschema.validate(args, OPERATIONS[name]['input_schema'])

def document(doc_id):
    if not re.fullmatch(r'doc-[a-f0-9]{24}', doc_id):
        raise ValueError('Неверный идентификатор документа.')
    return load_json(P / 'documents' / (doc_id + '.json'))

def info(doc):
    return {k: v for k, v in doc.items() if k != 'pages'}

def source(doc, reading):
    return {'provider': 'owner_supplied_local_file', 'platform_attribution': doc['platform'],
            'source_url': doc['source_url'], 'source_url_verified_by_adapter': False,
            'sha256': doc['sha256'], 'document_kind': doc['document_kind'],
            'reading_level': 'synthetic_test_text_only' if doc['document_kind'] == 'test_fixture' else reading,
            'rights_basis': doc['rights_basis'], 'license': doc['license'], 'license_verified_by_adapter': False}

def call(name, args):
    try:
        validate_args(name, args)
        result = _call(name, dict(args))
        result.setdefault('ok', True)
        result['tool'] = name
        result['checked_at'] = now()
        return result
    except (ValueError, FileNotFoundError) as e:
        return {'ok': False, 'tool': name, 'error': str(e), 'checked_at': now()}
    except Exception as e:
        # A request error can include credentials in a URL/header; never echo it.
        return {'ok': False, 'tool': name, 'error_type': type(e).__name__,
                'error': 'Операция не выполнена. Проверьте параметры и доступность внешнего сервиса.', 'checked_at': now()}

def _call(name, a):
    if name == 'service_status':
        verified = load_json(P / 'config' / 'verification.json')
        pending = ['written_access_permission']
        if not verified.get('real_source_documents_checked'): pending.append('real_owner_supplied_documents')
        if not verified.get('telegram_checked'): pending.append('owner_telegram_test')
        return {'mode': 'assisted_external_discovery_and_local_files', 'direct_site_access_enabled': False,
                'temporary_hold':load_json(P/'config/temporary-hold.json') if (P/'config/temporary-hold.json').exists() else {'active':False},
                'official_public_api_or_mcp': 'not_found_in_reviewed_primary_materials',
                'platforms': load_json(P / 'config' / 'sources.json'), 'tools': len(OPERATIONS),
                'profiles': len(load_json(P / 'config' / 'profiles.json')), 'inbox': str(P / 'inbox'),
                'local_reader': 'pypdf 6.19.0; text extraction only; no OCR',
                'verification': verified, 'pending': pending}
    if name == 'source_options':
        return {'platform': a['platform'], **platform(a['platform'])}
    if name == 'query_plan':
        s = platform(a['platform']); topic = a['topic'].strip()
        if not topic or len(topic) > 1200:
            raise ValueError('Тема должна содержать от 1 до 1200 знаков.')
        purpose = a.get('purpose', 'academic')
        return {'platform': a['platform'], 'purpose': purpose,
                'external_queries': [topic, '"' + topic + '"', topic + ' обзор', topic + ' методы'],
                'external_search_domains': [s['domain']], 'native_ui': s['manual_search'],
                'year_from': a.get('year_from'),
                'date_rule': 'Год проверяется по карточке/документу. Дата индексации и time_range Tavily не доказывают год публикации.',
                'business_rule': 'Проверьте отдельно права на применение в бизнесе и лицензию конкретной работы.' if purpose == 'business' else 'Проверьте лицензию и происхождение конкретной работы.',
                'coverage': 'Внешний указатель неполон. Этот план не запускает внутренний поиск площадки.'}
    if name == 'search_candidates':
        s = platform(a['platform']); query = a['query'].strip()
        if not query or len(query) > 1200:
            raise ValueError('Запрос должен содержать от 1 до 1200 знаков.')
        spec = importlib.util.spec_from_file_location('hermes_bn_ru_tavily', R / 'Tavily' / 'api.py')
        api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
        body = {'query': query, 'topic': 'general', 'search_depth': 'basic',
                'max_results': a.get('max_results', 5), 'include_domains': [s['domain']],
                'include_raw_content': False, 'include_answer': False}
        if 'time_range' in a: body['time_range'] = a['time_range']
        status, data = paced_request(lambda: api.request('search', body))
        if status != 200:
            return {'ok': False, 'http_status': status, 'provider': 'Tavily Search',
                    'direct_site_read': False, 'error': 'Внешний поиск не выполнен; автоматическая подмена источника отключена.'}
        records = []
        for row in data.get('results', []):
            url = row.get('url', ''); host = (urlsplit(url).hostname or '').lower()
            if host != s['domain'] and not host.endswith('.' + s['domain']):
                continue
            content = row.get('content') or ''
            records.append({'title': row.get('title'), 'url': url, 'candidate_type': classify_url(url, a['platform']),
                            'index_excerpt': content[:1800], 'excerpt_truncated': len(content) > 1800,
                            'date_as_returned_by_index': row.get('published_date'), 'date_verified': False,
                            'original_page_read': False, 'reading_level': 'external_search_excerpt_only'})
        result = {'provider': 'Tavily Search', 'platform': a['platform'], 'http_status': status,
                  'query': query, 'parameters': body, 'direct_site_read': False, 'records': records,
                  'coverage': 'Неполный внешний указатель. Количество результатов не равно числу работ в базе.',
                  'reading_level': 'external_search_excerpt_only'}
        path = P / 'data' / ('search-' + os.urandom(8).hex() + '.json')
        save_json(path, result); result['saved_result_file'] = str(path)
        return result
    if name == 'resolve_doi':
        doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', a['doi'].strip(), flags=re.I)
        if not re.fullmatch(r'10\.\d{4,9}/[^\s?#]+', doi, flags=re.I) or len(doi) > 300:
            raise ValueError('Передайте DOI вида 10.1234/identifier без дополнительных параметров.')
        url = 'https://api.crossref.org/works/' + quote(doi, safe='')
        response = paced_request(lambda: requests.get(url, headers={'User-Agent': 'HermesBN-RussianResearch/1.0'}, timeout=(10, 35), allow_redirects=False))
        if response.status_code != 200:
            return {'ok': False, 'http_status': response.status_code, 'provider': 'Crossref REST API',
                    'error': 'Метаданные не получены. DOI может относиться к другой регистрационной службе; 404 не доказывает отсутствие работы.'}
        m = response.json()['message']
        return {'provider': 'Crossref REST API', 'source_url': url, 'direct_target_site_read': False,
                'reading_level': 'crossref_metadata_only', 'doi': m.get('DOI'), 'doi_url': m.get('URL'),
                'title': m.get('title'), 'authors': [{k: v for k, v in x.items() if k in {'given', 'family', 'ORCID', 'affiliation'}} for x in m.get('author', [])],
                'publication_type': m.get('type'), 'journal_or_container': m.get('container-title'),
                'dates': {k: m[k] for k in ['issued', 'published', 'published-print', 'published-online', 'created', 'indexed'] if k in m},
                'licenses': m.get('license', []), 'relations': m.get('relation', {}), 'updates': m.get('update-to', []),
                'retraction_status': 'not_determined_by_this_lookup', 'abstract_read': False, 'full_text_read': False}
    if name == 'import_document':
        platform(a['platform']); valid_url(a['source_url'])
        if a['rights_confirmed'] is not True or not a['rights_basis'].strip():
            raise ValueError('Требуются подтверждение владельца и конкретное основание законного использования.')
        path = Path(a['path']).resolve(strict=True); inbox = (P / 'inbox').resolve()
        if not path.is_relative_to(inbox) or not path.is_file():
            raise ValueError('Допустимы только файлы в RussianResearch/inbox; ссылки за пределы папки запрещены.')
        suffix = path.suffix.lower()
        if suffix not in {'.pdf', '.txt', '.md', '.csv', '.ris', '.bib'}:
            raise ValueError('Поддерживаются PDF, TXT, MD, CSV, RIS и BibTeX.')
        if path.stat().st_size > 50_000_000:
            raise ValueError('Файл больше 50 МБ; подготовьте разрешённый фрагмент отдельно.')
        raw = path.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
        if suffix == '.pdf':
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                raise ValueError('Зашифрованный PDF: предоставьте разрешённую владельцем открываемую копию.')
            if len(reader.pages) > 500:
                raise ValueError('PDF больше 500 страниц; подготовьте разрешённый фрагмент отдельно.')
            pages = [page.extract_text() or '' for page in reader.pages]
            labels = reader.page_labels
        else:
            text = raw.decode('utf-8-sig')
            pages = text.split('\f'); labels = None
        key = sha + a['source_url'] + a['document_kind']
        doc_id = 'doc-' + hashlib.sha256(key.encode()).hexdigest()[:24]
        doc = {'document_id': doc_id, 'path': str(path), 'sha256': sha, 'imported_at': now(),
               'platform': a['platform'], 'source_url': a['source_url'], 'title': a['title'],
               'document_kind': a['document_kind'], 'rights_basis': a['rights_basis'], 'rights_confirmed_by_owner': True,
               'license': a.get('license', 'not_supplied'), 'year': a.get('year'), 'authors': a.get('authors', []),
               'bibliographic_metadata_verified': False, 'license_verified_by_adapter': False,
               'page_count': len(pages), 'page_labels': labels, 'page_characters': [len(x) for x in pages],
               'textless_pages': [i + 1 for i, x in enumerate(pages) if not x.strip()],
               'format': suffix, 'cloud_upload_performed': False, 'remote_download_performed': False,
               'extraction_scope': 'PDF text layer only; no OCR, image or visual table verification' if suffix == '.pdf' else 'UTF-8 text; form-feed separated segments; not necessarily printed pages',
               'pages': pages}
        save_json(P / 'documents' / (doc_id + '.json'), doc)
        return {'document': info(doc), 'source': source(doc, 'local_import_metadata_only'),
                'agent_has_read_text': False, 'warning': 'Импорт извлёк текст для последующих запросов; агент пока получил только метаданные.'}
    if name in {'document_info', 'read_pages', 'find_in_document', 'export_document_metadata'}:
        doc = document(a['document_id'])
        if name == 'document_info':
            return {'document': info(doc), 'source': source(doc, 'local_document_metadata_only')}
        if name == 'read_pages':
            pages = a['pages']; cap = a.get('max_chars_per_page', 8000); offset = a.get('offset', 0)
            if len(set(pages)) != len(pages) or any(p > doc['page_count'] for p in pages):
                raise ValueError('Нужны разные номера существующих физических страниц.')
            rows = []
            for page in pages:
                text = doc['pages'][page - 1]; part = text[offset:offset + cap]
                rows.append({'physical_page': page, 'page_label': doc['page_labels'][page - 1] if doc['page_labels'] else None,
                             'text': part, 'offset': offset, 'returned_characters': len(part),
                             'total_characters': len(text), 'has_more': offset + len(part) < len(text)})
            return {'document_id': doc['document_id'], 'title': doc['title'], 'pages': rows,
                    'source': source(doc, 'selected_local_page_text_only'), 'whole_document_read': False,
                    'visual_pdf_verified': False, 'extraction_scope': doc['extraction_scope']}
        if name == 'find_in_document':
            query = a['query'].strip()
            if not query or len(query) > 500:
                raise ValueError('Фраза должна содержать от 1 до 500 знаков.')
            flags = 0 if a.get('case_sensitive') else re.I
            hits = []; total = 0; cap = a.get('max_hits', 10)
            for page, text in enumerate(doc['pages'], 1):
                for match in re.finditer(re.escape(query), text, flags):
                    total += 1
                    if len(hits) < cap:
                        hits.append({'physical_page': page, 'character_offset': match.start(),
                                     'context': text[max(0, match.start() - 180):match.end() + 180]})
            return {'document_id': doc['document_id'], 'query': query, 'hits': hits, 'total_literal_hits': total,
                    'has_more_hits': total > len(hits), 'source': source(doc, 'local_literal_match_contexts_only'),
                    'coverage': 'Только извлечённый текст; отсутствие совпадений не исключает изображения, сканы и иную формулировку.',
                    'whole_document_read': False}
        fmt = a.get('format', 'json'); out = P / 'exports' / (doc['document_id'] + '.' + fmt)
        if fmt == 'json': save_json(out, {'document': info(doc), 'source': source(doc, 'local_bibliographic_metadata_only')})
        else:
            def clean(v): return str(v).replace('\r', ' ').replace('\n', ' ')
            rows = ['TY  - ' + ('THES' if doc['document_kind'] == 'dissertation' else 'GEN'), 'TI  - ' + clean(doc['title'])]
            rows += ['AU  - ' + clean(x) for x in doc['authors']]
            if doc['year']: rows.append('PY  - ' + str(doc['year']))
            rows += ['UR  - ' + clean(doc['source_url']), 'N1  - Owner-supplied metadata; not independently verified. Kind: ' + doc['document_kind'], 'ER  - ']
            out.parent.mkdir(parents=True, exist_ok=True, mode=0o700); out.write_text('\n'.join(rows) + '\n'); out.chmod(0o600)
        return {'export_file': str(out), 'format': fmt, 'bibliographic_metadata_verified': False, 'full_text_included': False}
    if name == 'permission_request':
        platform(a['platform']); path = P / 'обращения' / (a['platform'] + '.txt')
        return {'draft_file': str(path), 'draft': path.read_text(), 'sent': False,
                'next_step': 'Владелец направляет обращение по указанному официальному каналу и сохраняет письменный ответ.'}
    raise ValueError('Инструмент не реализован.')
