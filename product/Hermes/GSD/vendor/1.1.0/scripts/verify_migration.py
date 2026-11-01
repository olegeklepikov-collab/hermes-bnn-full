from pathlib import Path
import argparse
import subprocess, tempfile, json, os, sys, sqlite3, hashlib, datetime
NEW=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
p=argparse.ArgumentParser(description='Воспроизвести перенос фактической базы CLI 1.0.0 без сброса снимка и расхода')
p.add_argument('--previous',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
a=p.parse_args();OLD=a.previous.expanduser().resolve();REPORT=a.report.expanduser().resolve()
if OLD==NEW or not (OLD/'gsd.py').is_file() or json.loads((OLD/'release.json').read_text()).get('integration_version')!='1.0.0':p.error('Нужна распакованная исходная поставка интеграционного слоя 1.0.0')
if REPORT.exists() or REPORT.is_relative_to(NEW) or REPORT.is_relative_to(OLD):p.error('Нужен новый отчёт вне обеих поставок')
rows=[]
with tempfile.TemporaryDirectory(prefix='gsd-actual-migration-') as td:
    work=Path(td);env={**os.environ,'GSD_STATE_DIR':str(work/'state'),'GSD_TRUST_KEY_FILE':str(work/'key'),'GSD_HOST_POLICY':'','GSD_PROVIDER_CONFIG':''}
    def cli(root,*args,data=None):
        r=subprocess.run([sys.executable,'-I','-B',str(root/'gsd.py'),*args],input=json.dumps(data) if data is not None else None,capture_output=True,text=True,env=env,timeout=40)
        value=json.loads(r.stdout);rows.append({'operation':list(args),'release':'1.0.0' if root==OLD else '1.1.0','exit_code':r.returncode,'ok':value.get('ok',False)})
        return value
    a=cli(OLD,'init-state','--state-dir',env['GSD_STATE_DIR'],'--key-file',env['GSD_TRUST_KEY_FILE']);assert a['ok']
    case=json.loads((OLD/'examples/case_create.json').read_text())
    created=cli(OLD,'call','gsd_case_create',data=case);assert created['ok'];run=created['result']
    nxt=cli(OLD,'call','gsd_case_next',data={'run_id':run['run_id']});assert nxt['ok']
    # Use a recorded, unsuccessful actual attempt to establish nonzero cost/history without inventing a successful semantic result.
    changed=cli(OLD,'call','gsd_case_change',data={'run_id':run['run_id'],'request_id':'legacy-record-attempt','expected_store_revision':nxt['result']['store_revision'],'operation':'commit','payload':{'procedure_id':'BOOT.01','attempt_id':'LEGACY.ATTEMPT','status':'needs_data','output_ids':[],'expected_revision':0,'postcondition_observed':'Воспроизведение неуспешной попытки','reason':'Нужна реальная проверка','cost':2.5}})
    assert changed['ok'] and changed['result']['operation_accepted'],changed
    db=work/'state/state.sqlite3'
    with sqlite3.connect(db) as con: before=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(run['run_id'],)).fetchone()[0])
    denied=cli(NEW,'call','gsd_case_get',data={'run_id':run['run_id']});assert not denied['ok'] and denied['error']['code']=='STATE_MIGRATION_REQUIRED'
    path=work/'migration.json';path.write_text(json.dumps({'backup_path':str(work/'backup.sqlite3'),'apply':True}))
    migrated=cli(NEW,'host-command','migrate-state','--json',str(path),'--host-control');assert migrated['ok'],migrated
    with sqlite3.connect(db) as con: after=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(run['run_id'],)).fetchone()[0])
    assert before['snapshot']==after['snapshot']
    restored=cli(NEW,'call','gsd_case_get',data={'run_id':run['run_id']});assert restored['ok'],restored
    family=restored['result']['family']
    assert family['spent_steps']==before['snapshot']['spent_steps'] and family['spent_cost']==before['snapshot']['spent_cost']
    assert family['spent_steps']>0 and family['spent_cost']>0
    report={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,'scope':'Фактический исходный CLI слоя 1.0.0 создаёт запуск и неуспешную попытку; CLI 1.1.0 переносит и восстанавливает тот же снимок. Не производственная база.','original_snapshot_exact':True,'spent_steps':family['spent_steps'],'spent_cost':family['spent_cost'],'model_calls':0,'commands':rows}
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
