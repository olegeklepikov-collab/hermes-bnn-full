#!/usr/bin/env python3
"""Проверить исходное ядро в временной копии; не менять поставленные отчёты."""
import argparse, datetime, json, os
from pathlib import Path
import shutil, subprocess, sys, tempfile, time
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
out=a.output.expanduser().resolve()
if out.exists() or out.is_relative_to(ROOT):p.error('Выберите новый каталог результатов вне поставки')
out.mkdir(parents=True,mode=0o700)
rows=[]
with tempfile.TemporaryDirectory(prefix='gsd-original-check-') as td:
    engine=Path(td)/'engine';shutil.copytree(ROOT/'engine',engine)
    commands=[('integrity',['tools/verify_package.py','--release-integrity']),
        ('residual_integrity',['tools/verify_residual.py','--release-integrity']),
        ('system',['tests/run_all.py']),('remediation',['tests/test_remediation.py']),
        ('residual',['tests/test_residual.py',str(engine),str(out/'residual_results.json')])]
    for name,args in commands:
        start=time.monotonic();code=124
        try:
            run=subprocess.run([sys.executable,'-B',*args],cwd=engine,capture_output=True,text=True,encoding='utf-8',timeout=600,
                 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'})
            code=run.returncode;text=run.stdout+run.stderr
        except subprocess.TimeoutExpired:text='Превышено время проверки. Успех не установлен.\n'
        (out/(name+'.log')).write_text(text,encoding='utf-8')
        rows.append({'check':name,'exit_code':code,'seconds':round(time.monotonic()-start,3)})
        print(name,code,flush=True)
summary={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commands':rows,'passed':all(x['exit_code']==0 for x in rows),'original_bundle_modified':False}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
raise SystemExit(not summary['passed'])
