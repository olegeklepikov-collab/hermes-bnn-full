#!/usr/bin/env python3
"""Запустить локальные проверки и сохранить НОВЫЙ отчёт вне поставки."""
from pathlib import Path
import argparse, datetime, json, platform, sys, time, unittest
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'tests'))
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
report=a.report.expanduser().resolve()
if report.is_relative_to(ROOT) or report.exists():p.error('Отчёт должен быть новым файлом вне поставки')
rows=[]
class Result(unittest.TextTestResult):
    def startTest(self,test):self.started=time.perf_counter();super().startTest(test)
    def addSuccess(self,test):
        rows.append({'id':test.id(),'passed':True,'seconds':round(time.perf_counter()-self.started,4)});super().addSuccess(test)
    def addFailure(self,test,err):
        rows.append({'id':test.id(),'passed':False,'error':self._exc_info_to_string(err,test)});super().addFailure(test,err)
    def addError(self,test,err):
        rows.append({'id':test.id(),'passed':False,'error':self._exc_info_to_string(err,test)});super().addError(test,err)
    def addSubTest(self,test,subtest,err):
        if err:rows.append({'id':str(subtest),'passed':False,'error':self._exc_info_to_string(err,test)})
        super().addSubTest(test,subtest,err)
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
start=time.perf_counter();result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
data={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':platform.python_version(),'platform':platform.platform(),
 'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful(),
 'seconds':round(time.perf_counter()-start,3),'model_calls':0,'real_hermes':False,'real_ide':False,'telegram_e2e':False,
 'scope':'Локальные договоры, исходные конечные вычисления, отдельные процессы CLI/MCP и подставной PluginContext. Не содержательная приёмка модели.',
 'tests':rows}
report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(str(report));raise SystemExit(not result.wasSuccessful())
