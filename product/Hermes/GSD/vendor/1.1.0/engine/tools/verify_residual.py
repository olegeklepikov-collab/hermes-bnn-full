"""Проверить целостность и свидетельства редакции 3.0.3, не объявляя испытание LLM.

Не перезаписывает отчёты без явно заданного --out. Контрольные суммы подтверждают
соответствие заданной локальной базе, не подлинность автора или предметную истину.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from _base import ROOT, load_json


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(integrity: bool = False) -> dict:
    rows = []
    def check(name, fn):
        try:
            value = fn()
            if value is False:
                raise AssertionError(name)
            rows.append({'name': name, 'passed': True})
        except Exception as exc:
            rows.append({'name': name, 'passed': False, 'error': f'{type(exc).__name__}: {exc}'})
    def equal_files(mapping):
        return all((ROOT / path).is_file() and sha(ROOT / path) == expected
                   for path, expected in mapping.items())
    release = load_json(ROOT / 'data/release.json')
    check('Редакция и отдельная версия сравнительного договора', lambda:
          release['release'] == '3.0.3' and release['protocol_version'] == '3.0'
          and release['comparison_contract_version'] == '3.0.2')
    check('Исходники и незатронутые договоры сохранены', lambda:
          equal_files(load_json(ROOT / 'data/residual_baseline.json')['protected_files']))
    build = load_json(ROOT / 'data/instruction_build_manifest.json')
    check('Производные инструкции соответствуют канону', lambda:
          build['editorial_release'] == '3.0.3'
          and equal_files(build['inputs']) and equal_files(build['outputs']))
    binding = load_json(ROOT / 'reports/residual_binding.json')
    check('Фактические код и критерии связаны со свидетельствами', lambda:
          binding['actual_release'] == '3.0.3' and equal_files(binding['code_and_criteria'])
          and equal_files(binding['reports']))
    def closed_header():
        from jsonschema import Draft202012Validator
        d = load_json(ROOT / 'data/handoff.schema.json')
        Draft202012Validator.check_schema(d)
        return d['additionalProperties'] is False and set(d['required']) == set(d['properties'])
    check('Замкнутая форма заголовка передачи', closed_header)
    for file, n, expected_failed in [('residual_before_properties.json',545,14),
                                    ('residual_after_properties.json',545,0),
                                    ('residual_tests.json',470,0)]:
        def run_rows(file=file,n=n,expected_failed=expected_failed):
            d = load_json(ROOT/'reports'/file)
            return (d['tests']==n==len(d['rows'])
                    and len({r['id'] for r in d['rows']})==n
                    and d['failed']==expected_failed==sum(r['outcome']!='pass' for r in d['rows'])
                    and d['passed']==n-expected_failed)
        check('Первичные строки: '+file,run_rows)
    def same_criteria():
        b=load_json(ROOT/'reports/residual_before_properties.json')['rows']
        a=load_json(ROOT/'reports/residual_after_properties.json')['rows']
        return [(x['id'],x['criterion']) for x in b] == [(x['id'],x['criterion']) for x in a]
    check('545 критериев до и после не изменены',same_criteria)
    check('Прежние 615 критериев',lambda:
          (lambda d:d['test_count']==d['passed']==615 and d['failed']==0)(load_json(ROOT/'reports/residual_legacy615.json')))
    check('Прежние 331 критерий',lambda:
          (lambda d:d['test_count']==d['passed_count']==331 and d['failed_count']==0)(load_json(ROOT/'reports/residual_legacy331.json')))
    def regression():
        d=load_json(ROOT/'reports/verification_report.json')
        actual=[]
        for g in d['groups']:actual.extend(load_json(ROOT/g['path'])['tests'])
        return (d['test_count']==d['passed_count']==127 and d['failed_count']==0
                and actual==d['tests'] and all(x['passed'] for x in actual))
    check('127 завершённых групповых проверок',regression)
    def syntax():
        for path in [*ROOT.glob('tools/*.py'),*ROOT.glob('tests/*.py')]:
            compile(path.read_text(encoding='utf-8'),str(path),'exec')
        return True
    check('Синтаксис поставленных программ',syntax)
    check('Миграция и инструкция новой редакции поставлены',lambda:
          all((ROOT/p).is_file() for p in ['MIGRATION_3_0_3.md','REMEDIATION_REPORT.md','GSD_SYSTEM.md','tests/test_residual.py']))
    check('Модельная и профессиональная приёмки не присвоены',lambda:
          release['model_behavioral_acceptance']=='not_performed'
          and release['professional_acceptance']=='not_issued')
    if integrity:
        def file_integrity():
            d=load_json(ROOT/'manifest.json')
            listed={r['path']:r['sha256'] for r in d['files']}
            actual={str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*')
                    if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
            return listed==actual
        check('Полный состав и байты выпуска',file_integrity)
    return {'release':'3.0.3','checked_at':datetime.now(timezone.utc).isoformat(),
            'test_count':len(rows),'passed_count':sum(x['passed'] for x in rows),
            'failed_count':sum(not x['passed'] for x in rows),'checks':rows,
            'scope':'Согласованность поставки и первичных свидетельств; не новое исполнение всех тестов или модели.'}


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--release-integrity',action='store_true')
    ap.add_argument('--out',type=Path)
    args=ap.parse_args()
    report=verify(args.release_integrity)
    text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open('x',encoding='utf-8') as f:f.write(text)
    print(text)
    return 1 if report['failed_count'] else 0


if __name__=='__main__':
    raise SystemExit(main())
