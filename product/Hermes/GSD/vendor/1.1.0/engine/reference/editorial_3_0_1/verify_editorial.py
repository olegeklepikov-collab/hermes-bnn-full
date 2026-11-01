"""Проверить редакционную поставку 3.0.1 без заявления о предметной пригодности.

Контрольные отпечатки исходной поставки являются локальным основанием сравнения,
но не цифровой подписью автора. Проверка текста не доказывает эквивалентность
поведения произвольной языковой модели до и после редакционной правки.
"""
from __future__ import annotations
import ast
import hashlib
import json
import re
from pathlib import Path
from _base import ROOT, load_json, canonical


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WithoutDocstrings(ast.NodeTransformer):
    def strip(self, node):
        self.generic_visit(node)
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body = node.body[1:]
        return node
    visit_Module = strip
    visit_FunctionDef = strip
    visit_AsyncFunctionDef = strip
    visit_ClassDef = strip


def control(row):
    ignored = {'title', 'primary_operation', 'inputs', 'precondition', 'postcondition',
               'pass_action', 'applicability_rule', 'actor', 'negative_test_obligation'}
    value = {k: v for k, v in row.items() if k not in ignored}
    value['preconditions'] = {k: v for k, v in row['preconditions'].items() if k != 'specific'}
    return value


def active_text(text):
    return re.sub(r'<reference_corpus\b[^>]*>.*?</reference_corpus>', '', text, flags=re.S)


def main():
    baseline = load_json(ROOT / 'data/editorial_baseline.json')
    results = []
    def run(name, function):
        try:
            detail = function()
            results.append({'name': name, 'passed': True, 'detail': detail})
        except Exception as exc:
            results.append({'name': name, 'passed': False, 'error': str(exc)})
    def require(ok, message):
        if not ok:
            raise AssertionError(message)
    paths = [ROOT / p for p in ['COMMON.md', 'README.md', 'CHANGES_AND_ACCEPTANCE.md',
                               'WORKED_EXAMPLE.md', 'EDITORIAL_REPORT.md', 'PROCEDURES.md',
                               'G_SYSTEM.md', 'S_SYSTEM.md', 'DDx_SYSTEM.md', 'GSD_SYSTEM.md']]
    paths += sorted((ROOT / 'components').glob('*.md'))
    docs = {str(p.relative_to(ROOT)): active_text(p.read_text(encoding='utf-8')) for p in paths}
    def protected():
        for name, expected in baseline['protected_files'].items():
            require(sha((ROOT / name).read_bytes()) == expected, name)
        return {'files': len(baseline['protected_files']), 'comparison': 'byte_exact'}
    run('Дословные источники, архивы, точные реестры и схема не изменены', protected)
    def runtime():
        for name, expected in baseline['runtime_ast_sha256'].items():
            tree = WithoutDocstrings().visit(ast.parse((ROOT / name).read_text()))
            require(sha(ast.dump(tree, include_attributes=False).encode()) == expected, name)
        return {'modules': len(baseline['runtime_ast_sha256']), 'ignored': 'docstrings and comments'}
    run('Алгоритмы контроллера и исходные тесты не изменены', runtime)
    procedures = load_json(ROOT / 'data/procedures.json')['procedures']
    def controls():
        require({p['id']: control(p) for p in procedures} == baseline['procedure_controls'], 'Изменены управляющие поля')
        for p in procedures:
            require(p['inputs'] == p['preconditions']['specific'], p['id'] + ': вход и предусловие расходятся')
        return {'procedures': len(procedures), 'ids_dependencies_selectors_statuses': 'unchanged'}
    run('Управляющие поля 152 процедур сохранены', controls)
    def protocols():
        doc = load_json(ROOT / 'data/component_contracts.json')
        require([x['id'] for x in doc['contracts']] == baseline['component_ids'], 'Состав протоколов')
        for x in doc['contracts']:
            require(x['instruction_exact'] in (ROOT / x['source_path']).read_text(), x['id'])
            require(sha((ROOT / x['source_path']).read_bytes()) == x['source_sha256'], x['id'] + ': отпечаток')
        return len(doc['contracts'])
    run('Все 37 протоколов связаны с исправленными текстами', protocols)
    def quotes():
        new = {x['id']: x['sources'] for x in load_json(ROOT / 'data/adaptations.json')['adaptations']}
        require(new == baseline['adaptation_sources'], 'Изменена точная цитата')
        return {'adaptations': len(new)}
    run('Точные цитаты 11 адаптаций сохранены', quotes)
    def json_syntax():
        names = sorted(ROOT.rglob('*.json'))
        for p in names:
            load_json(p)
        return len(names)
    run('JSON читается без повторов ключей и недопустимых чисел', json_syntax)
    def encoding():
        for name, text in docs.items():
            for char in ('\ufeff', '\ufffd', '\x00'):
                require(char not in text, name + ': посторонний символ')
            require('\r' not in text, name + ': непоследовательный перенос строки')
            require(text.endswith('\n'), name + ': нет конечного переноса')
        return len(docs)
    run('Кодировка и окончания строк действующих документов согласованы', encoding)
    def whitespace():
        for name, text in docs.items():
            for i, line in enumerate(text.splitlines(), 1):
                require(line == line.rstrip(), f'{name}:{i}')
        return len(docs)
    run('В действующем тексте нет конечных пробелов', whitespace)
    def markup():
        for name, text in docs.items():
            fence = None
            for i, line in enumerate(text.splitlines(), 1):
                match = re.match(r'^\s*(`{3,}|~{3,})', line)
                if match:
                    mark = match.group(1)[0]
                    if fence is None: fence = mark
                    elif fence == mark: fence = None
                    continue
                if fence is None:
                    require(line.count('`') % 2 == 0, f'{name}:{i}: непарные обратные кавычки')
            require(fence is None, name + ': незакрытый блок кода')
        return len(docs)
    run('Блоки кода и технические выделения сбалансированы', markup)
    def alphabet():
        for name, text in docs.items():
            for word in re.findall(r'[A-Za-zА-Яа-яЁё]+', text):
                require(not (re.search('[A-Za-z]', word) and re.search('[А-Яа-яЁё]', word)), name + ': ' + word)
        return len(docs)
    run('В действующих словах нет смешения кириллицы и латиницы', alphabet)
    def notation():
        for name, text in docs.items():
            require('P.T.J.S.M.C' not in text, name + ': сокращена обязательная нотация')
            require('AD-02/AD-03' not in text, name + ': прежняя неверная ссылка')
            require('признак None' not in text, name + ': техническое None выдано за условие')
            require(not re.search(r'3C\.[GSD]\d{2}/\d{2}', text), name + ': неоднозначно сокращён маршрут')
        return len(docs)
    run('Нотация атома, ссылки адаптаций и маршруты записаны однозначно', notation)
    def ids():
        known = set(baseline['component_ids'])
        for name, text in docs.items():
            for ref in re.findall(r'3C\.[GSD]\d{2}', text):
                require(ref in known, name + ': ' + ref)
        return {'known_protocols': len(known)}
    run('Ссылки 3C ведут к существующим протоколам', ids)
    def adaptation_ids():
        known = {x['id'] for x in load_json(ROOT / 'data/adaptations.json')['adaptations']}
        for name, text in docs.items():
            for ref in re.findall(r'\bAD\d{2}\b', text):
                require(ref in known, name + ': ' + ref)
        text = docs['components/G_SYSTEM.md']
        require('`AD04` и `AD05`' in text and '`GA-02` и `GA-11` соответственно' in text, 'Неверное смысловое соответствие')
        return {'AD04': 'GA-02', 'AD05': 'GA-11'}
    run('AD04 и AD05 правильно сопоставлены с GA-02 и GA-11', adaptation_ids)
    def links():
        count = 0
        for name, text in docs.items():
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if target.startswith(('https:', 'http:', '#', 'mailto:')):
                    continue
                path = target.split('#', 1)[0]
                require((ROOT / name).parent.joinpath(path).exists(), name + ': ' + target)
                count += 1
        return {'local_markdown_links': count}
    run('Локальные ссылки Markdown разрешимы', links)
    def paths_in_prose():
        count = 0
        for name in ['README.md', 'WORKED_EXAMPLE.md', 'CHANGES_AND_ACCEPTANCE.md', 'EDITORIAL_REPORT.md']:
            text = re.sub(r'```.*?```', '', docs[name], flags=re.S)
            for value in re.findall(r'`([^`\n]+)`', text):
                if re.fullmatch(r'(?:sources|reference|components|data|reports|tools|tests|examples)/[A-Za-z0-9_.\-/]+', value):
                    if value != 'reports/editorial_verification.json':
                        require((ROOT / value).exists(), name + ': ' + value)
                    count += 1
        return count
    run('Названные в руководстве файлы и каталоги существуют', paths_in_prose)
    def profiles():
        from _base import PROFILES
        for p in PROFILES:
            require(p in docs['COMMON.md'], p)
        return list(PROFILES)
    run('Все шесть профилей сохранены', profiles)
    def reference_blocks():
        for name, expected in [('G_SYSTEM.md', ['G']), ('S_SYSTEM.md', ['S']), ('DDx_SYSTEM.md', []), ('GSD_SYSTEM.md', ['G', 'S'])]:
            text = (ROOT / name).read_text()
            actual = re.findall(r'<reference_corpus id="([GS])">\n(.*?)\n</reference_corpus>', text, re.S)
            require([x[0] for x in actual] == expected, name)
            for sid, content in actual:
                fname = 'Генератор мышления (монолит).md' if sid == 'G' else 'Строгое мышление (монолит).md'
                require(content == (ROOT / 'sources' / fname).read_text(), name + ': изменён источник')
        return {'builds': 4, 'exact_source_blocks': 4}
    run('Справочные блоки в сборках остаются дословными', reference_blocks)
    def idempotence():
        from assemble_instructions import build
        before = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths if p.name != 'EDITORIAL_REPORT.md'}
        build()
        for name, h in before.items():
            require(sha((ROOT / name).read_bytes()) == h, name + ': сборка не воспроизводится')
        return len(before)
    run('Повторная сборка воспроизводит те же инструкции', idempotence)
    def original_tests():
        d = load_json(ROOT / 'reports/verification_report.json')
        require(d['test_count'] == d['passed_count'] == 127 and d['failed_count'] == 0, 'Исходный набор не пройден')
        g = load_json(ROOT / 'reports/group_execution.json')
        require(len(g['groups']) == 7 and all(x['returncode'] == 0 for x in g['groups']), 'Не все процессы завершились успешно')
        return {'tests': 127, 'risk_combinations': d['profile_property_combinations'], 'completed_groups': 7}
    run('Повторный функциональный прогон завершён во всех семи группах', original_tests)
    def package_report():
        d = load_json(ROOT / 'reports/package_verification.json')
        require(d['test_count'] == d['passed_count'] == 16 and d['failed_count'] == 0, 'Проверка комплектации не пройдена')
        return {'checks': 16}
    run('Проверка комплектации пройдена', package_report)
    def clean_tree():
        bad = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
               if p.name in ('__pycache__', '.DS_Store', 'Thumbs.db') or p.suffix in ('.pyc', '.tmp', '.bak')]
        require(not bad, ','.join(bad))
        return 'Нет файлов кэша и случайных временных файлов'
    run('Поставка очищена от кэша и временных файлов', clean_tree)
    out = {'editorial_release': '3.0.1', 'protocol_version': '3.0',
           'scope': 'Редакционная структура, сохранность технических договоров и повторные локальные проверки. Не доказательство полной смысловой или эксплуатационной пригодности.',
           'test_count': len(results), 'passed_count': sum(x['passed'] for x in results),
           'failed_count': sum(not x['passed'] for x in results), 'checks': results,
           'semantic_adherence_of_arbitrary_agent': 'not_tested',
           'protected_quotation_language': 'preserved_verbatim'}
    (ROOT / 'reports/editorial_verification.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if out['failed_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
