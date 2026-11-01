"""Проверить текущую корректирующую поставку без записи и внешних эффектов.
--release-integrity дополнительно сверяет весь выпуск с manifest.json.
Успех не означает независимую профессиональную или поведенческую приёмку.
"""
from __future__ import annotations
import argparse,hashlib,json,ast
from pathlib import Path
from _base import ROOT,load_json
from jsonschema import Draft202012Validator
from corpus import Corpus
from triad import validate_comparison_review,StrictComponent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(integrity=False):
 rows=[]
 def check(ok,why):
  if not ok:raise AssertionError(why)
 def run(name,fn):
  try:detail=fn();rows.append({'name':name,'passed':True,'detail':detail})
  except Exception as e:rows.append({'name':name,'passed':False,'error':type(e).__name__+': '+str(e)})
 baseline=load_json(ROOT/'data/remediation_baseline.json');release=load_json(ROOT/'data/release.json')
 run('Паспорт текущего выпуска',lambda:check(release['release']=='3.0.2' and release['protocol_version']=='3.0','Версия'))
 def protected():
  for path,value in baseline['protected_files'].items():check(sha(ROOT/path)==value,path)
  return {'unchanged_files':len(baseline['protected_files'])}
 run('Исходные корпуса, глобальная схема, контроллер и прежние критерии не изменены',protected)
 def schema():
  sc=load_json(ROOT/'data/comparison_review.schema.json');Draft202012Validator.check_schema(sc)
  q=load_json(ROOT/'examples/triad_request.json');r=StrictComponent().compare(q['candidates'],q['observations'],scope=q['scope'])
  check(validate_comparison_review(r,q['candidates'],q['observations'],scope=q['scope']),'Review')
  return {'comparison_contract':r['comparison_contract_version'],'record_version':r['version']}
 run('Новая закрытая схема и её положительный пример',schema)
 def bound():
  b=load_json(ROOT/'reports/remediation_binding.json')
  for path,h in b['files'].items():check(sha(ROOT/path)==h,path)
  for path,h in b['reports'].items():check(sha(ROOT/'reports'/path)==h,path)
  return {'files':len(b['files']),'reports':len(b['reports'])}
 run('Результаты связаны с текущими файлами и исходами',bound)
 def test_report(name,total):
  x=load_json(ROOT/'reports'/name);check(x['test_count']==x['passed_count']==total and x['failed_count']==0,name)
  check(len(x['tests'])==total and all(t['passed'] for t in x['tests']),name+': строки')
  return {'passed':total}
 run('Исходная регрессия 127',lambda:test_report('verification_report.json',127))
 run('Адресные и соседние проверки 331',lambda:test_report('remediation_tests.json',331))
 def compare():
  before=load_json(ROOT/'reports/remediation_before_extended.json');after=load_json(ROOT/'reports/remediation_after_extended.json')
  check((before['test_count'],before['failed'])==(615,40),'Исходная серия')
  check((after['test_count'],after['passed'],after['failed'])==(615,615,0),'Новая серия')
  check([(x['id'],x['requirement']) for x in before['checks']]==[(x['id'],x['requirement']) for x in after['checks']],'Изменены критерии')
  return {'before_failures':40,'after_failures':0,'same_cases':615}
 run('Сравнение на неизменённых 615 критериях',compare)
 def u01():
  x=load_json(ROOT/'reports/remediation_after_independent.json');bad=[r['id'] for r in x['tests'] if not r['passed']]
  check(x['test_count']==42 and bad==['I-PROVENANCE'],'Неожиданный провал')
  return {'raw_passed':41,'raw_negative_preserved':'I-PROVENANCE','interpretation':'Исходный слишком широкий U01 не считается подтверждённым дефектом'}
 run('Неразрешённый старый критерий не скрыт и не переименован',u01)
 def findings():
  x=load_json(ROOT/'reports/remediation_findings.json');check({r['id'] for r in x['rows']}=={f'N{i:02d}' for i in range(1,9)},'Реестр')
  testids={r['id'] for r in load_json(ROOT/'reports/remediation_tests.json')['tests']}
  for r in x['rows']:check(bool(r['tests']) and set(r['tests'])<=testids,r['id'])
  check(set(x['external_unclosed'])=={'model_behavioral_evaluation','independent_professional_acceptance','production_deployment'},'Внешняя приёмка не должна закрываться')
  return {'findings':8,'external_acceptance_not_claimed':True}
 run('Восемь исправлений имеют адресные свидетельства и границы',findings)
 def modes():
  c=Corpus();out={}
  for mode in ('G','S','D','GS','GD','SD','GSD'):
   m=c.manifest(components=mode);out[mode]=c.assemble_context(m,byte_limit=4_000_000)['bytes']
  return out
 run('Семь согласованных контекстов реально собираются',modes)
 def policy():
  c=Corpus()
  for file in ['components/S_SYSTEM.md','S_SYSTEM.md','GSD_SYSTEM.md','./components/S_SYSTEM.md','README.md']:
   try:c.manifest(components='G',file_paths=[file])
   except ValueError:continue
   raise AssertionError(file+' принят')
  return {'rejected':5}
 run('Состав не расширяется через дополнительный файл',policy)
 def builds():
  m=load_json(ROOT/'data/instruction_build_manifest.json');check(m['editorial_release']=='3.0.2','Редакция сборки')
  for group in ('inputs','outputs'):
   for path,h in m[group].items():check(sha(ROOT/path)==h,path)
  return {'derivative_instructions':len(m['outputs'])}
 run('Производные инструкции согласованы с каноном',builds)
 def syntax():
  paths=list((ROOT/'tools').glob('*.py'))+list((ROOT/'tests').glob('*.py'))
  for p in paths:ast.parse(p.read_text())
  return {'program_files':len(paths)}
 run('Синтаксис всех программ поставки',syntax)
 def docs():
  for name in ['README.md','COMMON.md','MIGRATION_3_0_2.md','REMEDIATION_REPORT.md']:
   t=(ROOT/name).read_text();check('3.0.2' in t,name)
  check('Редакция текста: 3.0.1' not in (ROOT/'COMMON.md').read_text(),'Старый паспорт')
  return {'current_docs':4}
 run('Документация различает текущую и историческую редакции',docs)
 if integrity:
  def manifest():
   m=load_json(ROOT/'manifest.json');check(m['version']=='3.0.2','Манифест другой версии')
   expected={r['path']:r['sha256'] for r in m['files']};actual={str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
   check(expected==actual,'Состав или байты выпуска изменены');return {'files':len(expected)}
  run('Полный состав и контрольные суммы выпуска',manifest)
 return {'release':'3.0.2','test_count':len(rows),'passed_count':sum(x['passed'] for x in rows),'failed_count':sum(not x['passed'] for x in rows),'checks':rows,'scope':'Комплектация и привязка фактических локальных проверок; не независимая предметная приёмка'}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--release-integrity',action='store_true');args=p.parse_args();r=verify(args.release_integrity);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(bool(r['failed_count']))
