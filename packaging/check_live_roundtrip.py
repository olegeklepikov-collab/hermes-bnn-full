"""One real native TEST parent/worker/result cycle. Never fake a provider or reset a run."""
import argparse,json,sqlite3,subprocess
from pathlib import Path
import release_cli as release

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    manifest=release.verify_release(a.directory);registry=release.read(release.ROOT.parent/'.operator/environments.json')
    selected=registry['_qualified_candidates']['test'];qualification=release.read(selected['qualification'])
    if qualification['archive_sha256']!=manifest['archive']['sha256']:raise PermissionError('qualified_TEST_for_another_archive')
    home=Path(selected['installation'])/'Hermes';case=home.parent.parent/'live-roundtrip';evidence=case/'LIVE-ROUNDTRIP.json'
    if evidence.exists():
        old=release.read(evidence)
        if old['archive_sha256']!=manifest['archive']['sha256'] or release.digest(case/'cli.log')!=old['cli_log_sha256']:
            raise PermissionError('saved_live_observation_changed')
        print(json.dumps({'existing_receipt':str(evidence),'new_model_calls':0}));return
    if case.exists():raise PermissionError('unfinished_live_attempt_requires_observation_not_replay')
    if not (home/'data/auth.json').is_file():raise PermissionError('separate_TEST_authentication_required')
    case.mkdir(mode=0o700);env=release.clean_environment(Path(selected['home']))
    release.write(case/'attempt.json',{'archive_sha256':manifest['archive']['sha256'],'instance_id':selected['instance_id'],'state':'started','production_changed':False})
    created=subprocess.run([str(home/'bin/bd-bnn'),'create','Синтетическая проверка доставки дочернего продукта','--type','task','--description','Native TEST: parent, one worker, exact saved typed result. No external actions.','--json'],env=env,cwd=home,capture_output=True,text=True,check=True,timeout=90)
    bead=json.loads(created.stdout);release.write(case/'bead.json',bead)
    query=f'''Проверка отдельной TEST-среды. Выполни один настоящий дочерний запуск через work_team и прочитай его сохранённый продукт.
Сначала memory_working action=bind, beads_id={bead['id']}.
Затем work_team action=plan, request_id=roundtrip-1: одна задача key=arithmetic, title=Дочерний продукт, role=computation, goal=Проверь 13+29 и запиши формулу 13+29=42 в findings. Данные синтетические; sources, needs, limitations пусты. Не вызывай инструменты, сеть и дочерних агентов. Соблюдай типизированный контракт. resources={{}}, required_tools=[].
Выполни action=run, затем action=status. Обязательно прочитай action=result с task_id и expected_revision из status, offset=0, page_size=4096. При has_more=true читай дальше по next_offset с неизменными revision/product_sha256. succeeded не заменяет чтение findings.
Верни JSON: task_id, child_state, фактически прочитанные findings, product_sha256, evidence_status. Не запускай GSD, UDR, Foundation, Intake, terminal, execute_code, delegate_task или внешние действия. При отказе остановись. Нужные схемы: только memory_working и work_team, не более двух имён за запрос.'''
    query_path=case/'query.txt';query_path.write_text(query)
    with (case/'cli.log').open('w') as log:
        completed=subprocess.run([str(home/'bin/hermes'),'chat','--query-file',str(query_path),'--oneshot','--reasoning','xhigh','--max-turns','12','--run-budget','480','--format','stream-json','--in',str(home/'workspace')],env=env,cwd=home,stdout=log,stderr=subprocess.STDOUT,timeout=550)
    if completed.returncode:raise RuntimeError('native_CLI_failed_observe_saved_effects')
    events=[]
    for line in (case/'cli.log').read_text().splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
    final=next(v for v in events if v.get('type')=='result')
    if final['exit_code']!=0:raise RuntimeError('native_turn_failed')
    pages=[]
    for event in events:
        if event.get('type')=='tool_result' and event.get('name')=='work_team' and not event.get('is_error'):
            value=json.loads(event['output'])
            if isinstance(value,dict) and value.get('contract')=='BNNNativeTaskProductReadV1':pages.append(value)
    if not pages:raise RuntimeError('parent_did_not_read_saved_product')
    text='';first=pages[0]
    for page in pages:
        if page['offset']!=len(text) or any(page[k]!=first[k] for k in ['task_id','revision','product_sha256']):raise RuntimeError('product_pages_incomplete_or_changed')
        if release.hashlib.sha256(page['text'].encode()).hexdigest()!=page['fragment_sha256']:raise RuntimeError('fragment_hash_mismatch')
        text+=page['text']
    if pages[-1]['has_more'] or release.hashlib.sha256(text.encode()).hexdigest()!=first['product_sha256']:raise RuntimeError('product_not_completely_read')
    product=json.loads(text)
    if product['findings']!=['13+29=42'] or product['status']!='unreviewed':raise RuntimeError('unexpected_native_product')
    config=release.read(home/'Memory/settings.json');db_path=Path(config['state_root'])/'memory.sqlite'
    with sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=dict(db.execute('SELECT * FROM native_tasks WHERE profile_id=? AND id=?',(config['namespace']['profile_id'],first['task_id'])).fetchone())
        body=json.loads(row['body']);receipt=body['receipt']
        if row['root_sid']!=final['session_id'] or row['state']!='succeeded' or body['product']!=product or receipt['terminal_state']!='SUCCEEDED':raise RuntimeError('native_receipt_or_product_mismatch')
        if db.execute("SELECT COUNT(*) FROM native_tasks WHERE root_sid=? AND state IN ('running','unknown','launch_reserved')",(final['session_id'],)).fetchone()[0]:raise RuntimeError('workers_not_quiescent')
    answer=final['text'].strip()
    if answer.startswith('```'):answer='\n'.join(answer.splitlines()[1:-1])
    answer=json.loads(answer)
    if answer['findings']!=product['findings'] or answer['product_sha256']!=first['product_sha256']:raise RuntimeError('parent_answer_does_not_match_read_product')
    value={'contract':'BNNNativeRoundtripQualificationV1','archive_sha256':manifest['archive']['sha256'],'source_commit':manifest['source_commit'],'instance_id':selected['instance_id'],'profile_home':str(home/'data'),'model':'gpt-6.1-sol','provider':'openai-codex','reasoning_effort':'xhigh','parent_sid':final['session_id'],'child_sid':body['child_sid'],'task_id':first['task_id'],'bead_id':bead['id'],'product':product,'product_sha256':first['product_sha256'],'native_terminal_state':receipt['terminal_state'],'native_model_calls':receipt['usage_metadata'].get('api_calls'),'parent_received_complete_typed_product':True,'cli_log_sha256':release.digest(case/'cli.log'),'query_sha256':release.digest(query_path),'harness_sha256':release.digest(__file__),'operator_source_commit':release.git('rev-parse','HEAD'),'production_changed':False,'scope':'One synthetic parent/worker/result cycle; no scientific or external-service acceptance'}
    release.write(evidence,value);evidence.chmod(0o600)
    subprocess.run([str(home/'bin/bd-bnn'),'close',bead['id'],'--reason','Native worker result read completely by parent; synthetic qualification receipt saved.'],env=env,cwd=home,capture_output=True,text=True,check=True,timeout=90)
    print(json.dumps({'receipt':str(evidence),'native_terminal_state':'SUCCEEDED','parent_read_product':True}))

if __name__=='__main__':main()
