"""Проверяемый контекст: справочное основание не активирует чужой компонент."""
from __future__ import annotations
from copy import deepcopy
import hashlib
from .common import ROOT, ENGINE, BridgeError, canonical, digest, load, MAX_CONTEXT_BYTES


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ContextAssembler:
    def __init__(self, modules):
        self.base = modules['corpus'].Corpus()
        self.index = load(ROOT / 'contracts/engineering_sections.json')
        self.engineering_sections = {s['key']: s for s in self.index['sections']}
        self.procedures = {p['id']: p for p in load(ENGINE / 'data/procedures.json')['procedures']}
        self.registry = self.base.registry
        self.sources = self.base.sources

    def resolve_key(self, key):
        if not isinstance(key, str):
            raise BridgeError('UNKNOWN_REFERENCE', 'Адрес источника должен быть строкой')
        if key in self.engineering_sections:
            return key
        normalized = self.base.aliases.get(key, key)
        if normalized in self.base.entries or normalized in self.base.sections:
            return normalized
        if ':' in key:
            source, identifier = key.split(':', 1)
            if source in self.sources:
                try:
                    matches = self.base.lookup(source, identifier)
                except ValueError as exc:
                    raise BridgeError('UNKNOWN_REFERENCE', 'Не найден точный исходный идентификатор: ' + key) from exc
                if len(matches) != 1:
                    raise BridgeError('AMBIGUOUS_REFERENCE', 'Укажите точный адрес с номером строки: ' + key)
                return matches[0]['key']
        raise BridgeError('UNKNOWN_REFERENCE', 'Неизвестный адрес источника: ' + key)

    def exact(self, key):
        key = self.resolve_key(key)
        if key not in self.engineering_sections:
            return self.base.exact(key)
        meta = self.engineering_sections[key]
        raw = (ENGINE / self.index['source_path']).read_bytes()
        if sha(raw) != self.index['source_sha256']:
            raise BridgeError('SOURCE_CHANGED', 'Изменён инженерный источник')
        lines = raw.decode('utf-8').splitlines(keepends=True)
        text = ''.join(lines[meta['start_line']-1:meta['end_line']])
        if sha(text.encode()) != meta['sha256']:
            raise BridgeError('INDEX_CHANGED', 'Индекс не соответствует инженерному источнику')
        top = meta['number'].split('.')[0]
        parent = self.engineering_sections['engineering:section:' + top]
        entry = {**meta, 'source_identifier': meta['number'], 'owning_component': 'engineering',
                 'role': 'source_section', 'route': key}
        return {'entry': entry, 'definition': text,
                'parent_context': ''.join(lines[parent['start_line']-1:parent['end_line']]),
                'source_digest': self.index['source_sha256']}

    def operation_contract(self, key):
        if key not in self.engineering_sections:
            return self.base.operation_contract(self.resolve_key(key))
        x = self.exact(key)
        return {'id': key, 'version': '1', 'source_key': key, 'source_digest': x['source_digest'],
                'operation_exact_source': x['definition'], 'mandatory_context': x['parent_context'],
                'role': 'engineering_reference', 'requires_context_profile': 'engineering',
                'semantic_executor': 'host_agent_or_domain_reviewer', 'authority_granted': False}

    def manifest(self, *, components, entry_keys=(), file_paths=(), procedure_ids=(), profile='standard'):
        comps = set(components)
        if not comps or not comps <= set('GSD'):
            raise BridgeError('INVALID_COMPONENTS', 'Неверный состав')
        if profile not in ('standard', 'engineering'):
            raise BridgeError('INVALID_PROFILE', 'Неизвестный профиль контекста')
        selected = set(entry_keys)
        requested_procedures = set(procedure_ids)
        all_procedures = set()
        pending = sorted(requested_procedures)
        while pending:
            pid = pending.pop()
            if pid in all_procedures:
                continue
            if pid not in self.procedures:
                raise BridgeError('UNKNOWN_PROCEDURE', 'Неизвестная процедура: ' + pid)
            p = self.procedures[pid]
            all_procedures.add(pid)
            selected.update(p.get('source_anchors', []))
            pending.extend(p['dependencies'])
        for c in comps:
            selected.update(self.base.closure['mandatory_sections'][c])
        if profile == 'engineering':
            # Консервативное замыкание: весь неизменённый инженерный исходник.
            # Не выдаём автоматически найденные ссылки за доказанно полный граф.
            selected.update(k for k, s in self.engineering_sections.items() if s['level'] == 2)
        pending = list(selected)
        canonical_keys = set()
        resolutions = {}
        while pending:
            key = pending.pop()
            requested_key = key
            x = self.exact(key)
            key = x['entry']['key']
            if key != requested_key:
                resolutions[requested_key] = key
            if key in canonical_keys:
                continue
            canonical_keys.add(key)
            entry = x['entry']
            source = entry.get('source', key.split(':')[0])
            if source == 'engineering' and profile != 'engineering':
                raise BridgeError('ENGINEERING_PROFILE_REQUIRED', 'Для инженерного источника нужен profile=engineering')
            lookup_key = source + ':' + entry['source_identifier']
            for dep in self.base.closure['dependencies'].get(lookup_key, []):
                sid, identifier = dep.split(':', 1)
                matches = self.base.lookup(sid, identifier)
                if len(matches) != 1:
                    raise BridgeError('AMBIGUOUS_REFERENCE', 'Неоднозначная обязательная ссылка: ' + dep)
                pending.append(matches[0]['key'])
        paths = ['COMMON.md', 'data/context_closure.json', 'data/adaptations.json',
                 'data/instruction_file_roles.json'] + [f'components/{c}_SYSTEM.md' for c in sorted(comps)] + list(file_paths)
        roles = load(ENGINE / 'data/instruction_file_roles.json')['files']
        files = []
        seen_paths = set()
        for rel in sorted(set(paths)):
            path = (ENGINE / rel).resolve()
            if not path.is_relative_to(ENGINE.resolve()) or not path.is_file():
                raise BridgeError('UNSAFE_CONTEXT_PATH', 'Путь вне исходной поставки')
            rel = path.relative_to(ENGINE).as_posix()
            if rel not in roles or not set(roles[rel]) <= comps:
                raise BridgeError('INACTIVE_INSTRUCTION', 'Нельзя подключить активную инструкцию отсутствующего компонента')
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            raw = path.read_bytes()
            files.append({'path': rel, 'sha256': sha(raw), 'bytes': len(raw),
                          'role': 'active_instruction', 'required_components': roles[rel]})
        entries = []
        for key in sorted(canonical_keys):
            x = self.exact(key)
            owner = x['entry']['owning_component']
            entries.append({'key': key, 'source_sha256': x['source_digest'],
                'definition_sha256': sha(x['definition'].encode()), 'parent_sha256': sha(x['parent_context'].encode()),
                'source_owner': owner, 'use': 'reference_only', 'executes_component': False,
                'foreign_component_reference': owner in set('GSD') and owner not in comps})
        contracts = [{'id': pid, 'sha256': digest(self.procedures[pid]),
                      'owning_component': self.procedures[pid]['owning_component'],
                      'execution': 'local_when_ready' if self.procedures[pid]['owning_component'] in comps else 'external_product_required_when_active'}
                     for pid in sorted(all_procedures)]
        rule_path = 'docs/integration/EXECUTION_CONTRACT.md'
        rule_raw = (ROOT / rule_path).read_bytes()
        result = {'version': 'gsd.integration.context/1.1', 'components': sorted(comps),
            'profile': profile, 'selection': {'entry_keys': sorted(set(entry_keys)),
                'procedure_ids': sorted(requested_procedures), 'file_paths': sorted(set(file_paths))},
            'files': files, 'bridge_files': [{'path': rule_path, 'sha256': sha(rule_raw)}],
            'entries': entries, 'procedure_contracts': contracts,
            'source_resolutions': [{'requested':k, 'resolved':v, 'rule':'unique_source_identifier_or_registered_alias'}
                                   for k,v in sorted(resolutions.items())],
            'corpus_digest': digest(self.registry['sources']),
            'engineering_closure': ({'strategy': 'entire_source_conservative',
                'source_sha256': self.index['source_sha256'], 'source_bytes': self.index['source_bytes'],
                'mandatory_core': self.index['mandatory_core'], 'index_sha256': sha((ROOT/'contracts/engineering_sections.json').read_bytes())}
                if profile == 'engineering' else None),
            'meaning': 'Полнота доставки, исполнение, предметная проверка и полномочие являются разными обязательствами'}
        result['digest'] = digest(result)
        return result

    def verify_manifest(self, manifest, *, loaded_files=None, loaded_entries=None):
        if digest({k: v for k, v in manifest.items() if k != 'digest'}) != manifest.get('digest'):
            raise BridgeError('MANIFEST_CHANGED', 'Подменён манифест контекста')
        current = self.manifest(components=manifest['components'], profile=manifest['profile'], **manifest['selection'])
        if current != manifest:
            raise BridgeError('STALE_CONTEXT', 'Манифест устарел или неполон')
        if loaded_files is not None:
            expected = {'engine/' + x['path']: x['sha256'] for x in manifest['files']}
            expected.update({x['path']: x['sha256'] for x in manifest['bridge_files']})
            if manifest['profile'] == 'engineering':
                expected['engine/' + self.index['source_path']] = self.index['source_sha256']
            if loaded_files != expected:
                raise BridgeError('INCOMPLETE_CONTEXT', 'Загружены не все обязательные файлы')
        if loaded_entries is not None and loaded_entries != {
            x['key']: (x['definition_sha256'], x['parent_sha256']) for x in manifest['entries']}:
            raise BridgeError('INCOMPLETE_CONTEXT', 'Не подтверждены точные определения и родительский контекст')
        return True

    def assemble_context(self, manifest, *, byte_limit):
        if type(byte_limit) is not int or not 0 < byte_limit <= MAX_CONTEXT_BYTES:
            raise BridgeError('CONTEXT_LIMIT', 'Нужен положительный предел не более 8 МиБ')
        self.verify_manifest(manifest)
        parts, files, entries, seen = [], {}, {}, set()
        for row in manifest['files']:
            raw = (ENGINE / row['path']).read_bytes()
            files['engine/' + row['path']] = sha(raw)
            parts.append('\n<active_instruction path="' + row['path'] + '">\n' + raw.decode() + '\n</active_instruction>\n')
        for row in manifest['bridge_files']:
            raw = (ROOT / row['path']).read_bytes()
            files[row['path']] = sha(raw)
            parts.append('\n<integration_contract>\n' + raw.decode() + '\n</integration_contract>\n')
        if manifest['profile'] == 'engineering':
            raw = (ENGINE / self.index['source_path']).read_bytes()
            files['engine/' + self.index['source_path']] = sha(raw)
            parts.append('\n<engineering_source scope="engineering_operation" authority_granted="false">\n' + raw.decode() + '\n</engineering_source>\n')
        for row in manifest['entries']:
            x = self.exact(row['key'])
            a, b = sha(x['definition'].encode()), sha(x['parent_context'].encode())
            entries[row['key']] = (a, b)
            engineering = x['entry'].get('source') == 'engineering'
            if b not in seen and not engineering:
                parts.append('\n<reference_context source="' + x['entry'].get('source', row['key'].split(':')[0]) +
                    '" use="reference_only" executes_component="false">\n' + x['parent_context'] + '\n</reference_context>\n')
                seen.add(b)
        for row in manifest['procedure_contracts']:
            parts.append('\n<procedure_contract execution="' + row['execution'] + '">\n' +
                canonical(self.procedures[row['id']]).decode() + '\n</procedure_contract>\n')
        self.verify_manifest(manifest, loaded_files=files, loaded_entries=entries)
        text = ''.join(parts)
        if len(text.encode()) > byte_limit:
            raise BridgeError('CONTEXT_LIMIT', 'Полное замыкание не помещается; нужен больший контекст или отдельно проверенное разделение, не обрезка')
        return {'manifest_digest': manifest['digest'], 'text': text, 'bytes': len(text.encode()),
                'loaded_files': files, 'loaded_entries': entries, 'text_sha256': sha(text.encode()),
                'semantic_adherence': 'not_inferred_from_loading', 'model_delivery_verified': False,
                'instruction_priority': 'bounded_by_actual_host_policy'}
