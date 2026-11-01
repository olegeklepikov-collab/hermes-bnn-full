"""Проверка состава поставки; не повторяет и не заменяет поведенческие испытания.

Без параметров проверяет текущие договоры, источники, производные инструкции и
существующие отчёты. --release-integrity дополнительно сверяет неизменённую
поставку с manifest.json; этот хеш-манифест не удостоверяет автора.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from _base import ROOT, load_json, digest, PROFILES
from build_contracts import check as check_contracts
from corpus import Corpus
from records import validate_case


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def verify(release_integrity: bool = False) -> dict:
    results = []
    def run(name, fn):
        try:
            detail = fn()
            results.append({'name': name, 'passed': True, 'detail': detail})
        except Exception as exc:
            results.append({'name': name, 'passed': False,
                            'error': type(exc).__name__ + ': ' + str(exc)})

    corpus = Corpus()
    registry = corpus.registry
    run('Форма схемы и разрешимость каталога', check_contracts)

    def python_syntax():
        paths = sorted([*ROOT.glob('tools/*.py'), *ROOT.glob('tests/*.py')])
        for path in paths:
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        return {'compiled_sources': len(paths), 'scope': 'синтаксис, не исполнение'}
    run('Синтаксис всех поставленных программ', python_syntax)

    def sources():
        require(len(registry['sources']) == 4, 'Нужны четыре исходных источника')
        for source in registry['sources']:
            path = ROOT / source['path']
            require(sha(path) == source['sha256'], source['path'])
            require(path.stat().st_size == source['bytes'], source['path'] + ': размер')
        return {'count': 4, 'byte_exact_against_recorded_digests': True}
    run('Побайтовая сохранность четырёх источников', sources)

    def sections():
        doc = load_json(ROOT / 'data/source_sections.json')
        rows = doc['sections']
        require(len(rows) == doc['section_count'] == 297, 'Число разделов')
        for sid in ('strict', 'generative', 'delivery'):
            parts = sorted((x for x in rows if x['source'] == sid), key=lambda x: x['start_line'])
            require(parts[0]['start_line'] == 1, 'Утрачен первый фрагмент')
            for left, right in zip(parts, parts[1:]):
                require(left['end_line'] + 1 == right['start_line'], 'Пересечение/разрыв разделов')
            raw = ''.join(x['text'] for x in parts).encode('utf-8')
            require(raw == (ROOT / corpus.sources[sid]['path']).read_bytes(), 'Неверная сборка ' + sid)
        return {'sections': len(rows), 'reconstructed_sources': 3}
    run('Восстановление трёх монолитов из 297 разделов', sections)

    def named_entries():
        require(len(corpus.entries) == registry['entry_count'] == 1728, 'Число именованных вхождений')
        for key, item in corpus.entries.items():
            exact = corpus.exact(key)
            require(exact['definition'].rstrip('\r\n') == item['exact_text'].rstrip('\r\n'), key)
            require(bool(exact['parent_context'].strip()), 'Нет родительского контекста ' + key)
        for alias, target in corpus.aliases.items():
            require(target in corpus.entries, 'Отсутствующий адрес ' + alias)
        return {'named_occurrences': len(corpus.entries), 'old_aliases': len(corpus.aliases),
                'semantic_independent_tests_not_implied': True}
    run('Точные определения, родительский контекст и прежние адреса', named_entries)

    def context_closure():
        sizes = {}
        for components in ('G', 'S', 'D', 'GS', 'GD', 'SD', 'GSD'):
            manifest = corpus.manifest(components=components)
            text = corpus.assemble_context(manifest, byte_limit=4_000_000)
            sizes[components] = text['bytes']
        for parent, dependencies in corpus.closure['dependencies'].items():
            sid, identifier = parent.split(':', 1)
            require(len(corpus.lookup(sid, identifier)) == 1, 'Неоднозначный родитель ' + parent)
            for dep in dependencies:
                sid, identifier = dep.split(':', 1)
                require(len(corpus.lookup(sid, identifier)) == 1, 'Неоднозначная зависимость ' + dep)
        return {'assembled_bytes_by_mode': sizes, 'scope': 'объявленные зависимости, не доказательство понимания'}
    run('Реальная сборка объявленного контекста семи составов', context_closure)

    def protocols():
        doc = load_json(ROOT / 'data/component_contracts.json')
        rows = doc['contracts']
        require(len(rows) == doc['count'] == 37, 'Число протоколов')
        require(len({x['id'] for x in rows}) == len(rows), 'Дубли протоколов')
        for row in rows:
            path = ROOT / row['source_path']
            require(sha(path) == row['source_sha256'], row['id'] + ': версия инструкции')
            require(row['instruction_exact'] in path.read_text(), row['id'] + ': текст')
            require(row['owning_component'] in ('G', 'S', 'D'), row['id'] + ': владелец')
        return {'component_protocols': len(rows)}
    run('37 компонентных протоколов связаны с инструкциями', protocols)

    def leaves():
        doc = load_json(ROOT / 'data/semantic_leaves.json')
        parents = {x['id'] for x in load_json(ROOT / 'data/component_contracts.json')['contracts']}
        require(len(doc['leaves']) == doc['count'] == 31, 'Число дочерних проверок')
        for row in doc['leaves']:
            require(row['parent'] in parents, row['id'] + ': родитель')
            if row.get('source_key'):
                exact = corpus.exact(row['source_key'])
                require(exact['source_digest'] == row['source_digest'], row['id'] + ': исходник')
                require(exact['definition'] == row['operation_exact_source'], row['id'] + ': точная операция')
        return {'separate_subchecks': 31}
    run('Отдельная адресация V/A/R, GG, GA и строгих G', leaves)

    def adaptations():
        doc = load_json(ROOT / 'data/adaptations.json')
        require(len(doc['adaptations']) == doc['count'] == 11, 'Число адаптаций')
        count = 0
        for row in doc['adaptations']:
            for reference in row['sources']:
                path = ROOT / reference['path']
                require(sha(path) == reference['source_sha256'], row['id'] + ': исходная версия')
                actual = '\n'.join(path.read_text().splitlines()[reference['start_line']-1:reference['end_line']])
                require(actual == reference['exact_excerpt'], row['id'] + ': границы цитаты')
                count += 1
            require(bool(row['scope'].strip()) and bool(row['local_rule'].strip()), row['id'] + ': область')
        return {'adaptations': 11, 'exact_fragments': count,
                'external_domain_authority_not_implied': True}
    run('Адаптации явно связаны с исходными формулировками', adaptations)

    def derived_builds():
        manifest = load_json(ROOT / 'data/instruction_build_manifest.json')
        for group in ('inputs', 'outputs'):
            for path, expected in manifest[group].items():
                require(sha(ROOT / path) == expected, 'Изменён ' + path)
        g = (ROOT / 'sources/Генератор мышления (монолит).md').read_text()
        s = (ROOT / 'sources/Строгое мышление (монолит).md').read_text()
        for filename, has_g, has_s in [('G_SYSTEM.md', True, False), ('S_SYSTEM.md', False, True),
                                       ('DDx_SYSTEM.md', False, False), ('GSD_SYSTEM.md', True, True)]:
            text = (ROOT / filename).read_text()
            require((g in text) == has_g and (s in text) == has_s, filename + ': скрытый/утраченный корпус')
            if has_g: require(text.count(g) == 1, filename + ': дублирование G')
            if has_s: require(text.count(s) == 1, filename + ': дублирование S')
        from assemble_instructions import render_catalog
        expected = render_catalog(load_json(ROOT / 'data/procedures.json')['procedures'])
        require((ROOT / 'PROCEDURES.md').read_text() == expected, 'Каталог расходится со схемой')
        return {'instruction_builds': 4, 'catalog_matches': True}
    run('Самостоятельные и совместная сборки не расходятся с каноном', derived_builds)

    def layer_coverage():
        doc = load_json(ROOT / 'data/layer_coverage.json')
        require(len(doc['rows']) == doc['count'] == 54, 'Число крупных разделов')
        for row in doc['rows']:
            require((ROOT / row['instruction']).is_file(), 'Нет инструкции')
            require(row['behavioral_full_coverage'] is False, 'Необоснованная полная поведенческая проверка')
        return {'major_source_sections': 54}
    run('Карта крупных исходных слоёв и границы покрытия', layer_coverage)

    def example_cases():
        paths = sorted(ROOT.glob('examples/0[1-5]_*.json'))
        require(len(paths) == 5, 'Не хватает примеров')
        for path in paths:
            case = load_json(path)
            require(case['data_kind'] == 'synthetic', 'Пример потерял искусственный статус')
            issues = validate_case(case)
            require(not issues, path.name + ': ' + ','.join(x.code for x in issues))
        return {'valid_synthetic_cases': len(paths)}
    run('Пять подробных искусственных случаев соответствуют текущей схеме', example_cases)

    def test_reports():
        report = load_json(ROOT / 'reports/verification_report.json')
        require(report['test_count'] == report['passed_count'] == 127 and report['failed_count'] == 0, 'Итоги тестов')
        require(report['profile_property_combinations'] == 192, 'Сочетания профилей')
        actual_tests = []
        for group in report['groups']:
            part = load_json(ROOT / group['path'])
            require(digest(part) == group['report_digest'], group['path'] + ': изменён отчёт')
            require(part['failed_count'] == 0, group['path'] + ': отказ')
            actual_tests.extend(part['tests'])
        require(actual_tests == report['tests'], 'Сводка не совпадает с группами')
        require(len({x['name'] for x in actual_tests}) == 127, 'Повтор имени испытания')
        require({x['profile'] for x in report['traces']} == set(PROFILES), 'Профильные циклы')
        return {'upper_level_tests': 127, 'risk_profile_combinations_inside_tests': 192,
                'synthetic_profile_cycles': len(report['traces'])}
    run('Сводный отчёт подтверждён фактическими групповыми отчётами', test_reports)

    def finite_benchmark():
        report = load_json(ROOT / 'reports/finite_benchmark.json')
        require(report['data_kind'] == 'synthetic' and len(report['cases']) == 6, 'Граница сравнения')
        totals = {}
        for method in ('first_candidate', 'simple_program', 'GSD'):
            totals[method] = sum(row['measurements'][method]['matches_predeclared_oracle'] for row in report['cases'])
        require(totals == {'first_candidate': 2, 'simple_program': 6, 'GSD': 6}, 'Результат конечного сравнения')
        return {'correct_out_of_six': totals, 'general_performance_advantage_not_established': True}
    run('Конечное сравнение сохраняет границу и неудобный результат', finite_benchmark)

    def findings():
        report = load_json(ROOT / 'reports/findings_resolution.json')
        require({x['id'] for x in report['rows']} == {f'F{i:02}' for i in range(1, 27)}, 'Реестр F01–F26')
        test_names = {x['name'] for x in load_json(ROOT / 'reports/verification_report.json')['tests']}
        for row in report['rows']:
            require(set(row['direct_test_names']) <= test_names, row['id'] + ': отсутствует указанный тест')
            if row['id'] in ('F24', 'F26'):
                require('открыт' in row['status'], row['id'] + ': необоснованно закрыта внешняя пригодность')
        return {'findings_addressed': 26, 'broad_fitness_not_closed': ['F24', 'F26']}
    run('Все замечания имеют изменение и честную границу приёмки', findings)

    def readme_files():
        required = ['tools/verify_package.py', 'tools/engine.py', 'tools/triad.py', 'tools/migrate.py',
                    'tools/build_contracts.py', 'tools/assemble_instructions.py', 'tools/benchmark.py',
                    'tests/run_all.py', 'examples/strict_derivation.json', 'examples/triad_request.json',
                    'WORKED_EXAMPLE.md', 'CHANGES_AND_ACCEPTANCE.md', 'requirements.txt']
        for path in required: require((ROOT / path).is_file(), 'Отсутствует ' + path)
        for path in ROOT.glob('tools/*.py'):
            text = path.read_text()
            require(('/mnt/data/' + 'work/') not in text, 'Внешний рабочий путь в ' + path.name)
        return {'required_files': len(required), 'external_build_workdir_not_required': True}
    run('Команды документации имеют поставленные исполнители', readme_files)

    if release_integrity:
        def integrity():
            manifest = load_json(ROOT / 'manifest.json')
            for row in manifest['files']:
                require(sha(ROOT / row['path']) == row['sha256'], 'Изменён файл поставки ' + row['path'])
            return {'files': len(manifest['files']), 'author_authenticity_not_proven': True}
        run('Неизменённость выпуска относительно локального манифеста', integrity)

    report = {'version': '3.0', 'date': '2026-09-12',
              'scope': 'Комплектность, целостность, формы, ссылки и согласованность существующих отчётов; не новые предметные или поведенческие испытания.',
              'test_count': len(results), 'passed_count': sum(x['passed'] for x in results),
              'failed_count': sum(not x['passed'] for x in results), 'checks': results}
    # Дополнительная проверка неизменённости не меняет проверяемый отчёт выпуска.
    if not release_integrity:
        (ROOT / 'reports/package_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-integrity', action='store_true')
    args = parser.parse_args()
    report = verify(args.release_integrity)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report['failed_count'] else 0)
