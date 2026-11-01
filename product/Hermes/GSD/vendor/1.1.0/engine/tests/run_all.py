"""Полный набор в изолированных процессах: ядро и шесть профильных циклов.
Изоляция разделяет состояние испытателей; результаты не считаются независимыми
предметными наблюдениями и не оценивают свободное поведение языковой модели.
"""
from pathlib import Path
import subprocess,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
PROFILES=['eMVP','MVP','Standard','eStandard','High Stakes','Critical Infrastructure']
parts=[];runs=[]
jobs=[(['--skip-traces'],'core_verification_report.json')]+[(['--trace-profile',p],'trace_'+p.replace(' ','_')+'.json') for p in PROFILES]
for args,file in jobs:
    start=time.perf_counter();res=subprocess.run([sys.executable,str(ROOT/'tests/test_system.py'),*args],cwd=ROOT,text=True,capture_output=True,timeout=100)
    label='core' if args[0]=='--skip-traces' else args[1].replace(' ','_')
    (ROOT/'reports'/('test_run_'+label+'.log')).write_text(res.stdout+res.stderr,encoding='utf-8')
    if res.returncode:print(res.stdout,res.stderr);raise SystemExit(res.returncode)
    part=json.loads((ROOT/'reports'/file).read_text());parts.append(part);runs.append({'group':label,'returncode':res.returncode,'seconds':time.perf_counter()-start})
    print(label,part['passed_count'],'/',part['test_count'],flush=True)
sys.path.insert(0,str(ROOT/'tools'))
from collect_reports import collect
report=collect()
(ROOT/'reports/group_execution.json').write_text(json.dumps({'version':'3.0','groups':runs,'scope':'Время локальных групп, не стоимость использования агента'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:report[k] for k in ('test_count','passed_count','failed_count')},ensure_ascii=False))
