import asyncio,json,sys,uuid
from pathlib import Path
from contextlib import AsyncExitStack
from mcp import ClientSession,StdioServerParameters,types
from mcp.client.stdio import stdio_client
Z=Path(__file__).resolve().parents[1];R=Z.parent;sys.path.insert(0,str(Z));from workspace_api import dump
proof=json.loads((Z/'checks/native-verification.json').read_text()) if (Z/'checks/native-verification.json').exists() else {};tools={}
def parse(result):
 if result.structured_content:return result.structured_content
 for c in result.content:
  if c.type=='text':
   try:return json.loads(c.text)
   except:continue
 return {'text':'\n'.join(c.text for c in result.content if c.type=='text')}
async def main():
 async with AsyncExitStack() as stack:
  clients={}
  for kind,cmd in [('beads','beads-bn-scoped-mcp'),('dolt','dolt-bn-mcp')]:
   streams=await stack.enter_async_context(stdio_client(StdioServerParameters(command=str(R/'bin'/cmd))))
   c=await stack.enter_async_context(ClientSession(streams[0],streams[1],read_timeout_seconds=180));init=await c.initialize();catalog=await c.list_tools();await c.send_ping();clients[kind]=c;tools[kind]={t.name:t for t in catalog.tools};dump((R/'Beads' if kind=='beads' else Z)/'checks/scoped-catalog.json',{'initialize':init.model_dump(mode='json',by_alias=True),'tools':catalog.model_dump(mode='json',by_alias=True)})
  async def test(key,kind,name,args={},error=False):
   if key in proof and proof[key]['passed']:
    return parse(types.CallToolResult.model_validate(proof[key]['result']))
   r=await clients[kind].call_tool(name,args);d=r.model_dump(mode='json',by_alias=True);proof[key]={'server':kind,'tool':name,'arguments':args,'result':d,'expected_error':error,'passed':bool(r.is_error)==error};dump(Z/'checks/native-verification.json',proof);print(key,'PASS' if proof[key]['passed'] else 'FAIL',flush=True)
   if not proof[key]['passed']:raise RuntimeError(key+': '+str(parse(r))[:1800])
   return parse(r)
  # Beads task lifecycle and blockers.
  await test('beads-stats','beads','stats')
  epic=await test('beads-create-epic','beads','create',{'title':'Синтетическая проверка подключения Beads и Dolt','issue_type':'epic','priority':2,'description':'Только тест интерфейсов; научное исследование не выполняется.','brief':False})
  def ident(d):
   if isinstance(d,dict):
    if isinstance(d.get('id'),str):return d['id']
    for v in d.values():
     q=ident(v)
     if q:return q
   if isinstance(d,list):
    for v in d:
     q=ident(v)
     if q:return q
   return None
  ep=ident(epic);assert ep
  a=ident(await test('beads-create-a','beads','create',{'title':'Синтетическая проверка источника данных','priority':2,'description':'Проверка структуры, не чтение статьи.','brief':False}))
  b=ident(await test('beads-create-b','beads','create',{'title':'Синтетическая проверка версий таблицы','priority':2,'description':'Зависит от задачи источника.','brief':False}))
  dump(R/'Beads/checks/test-issue-ids.json',{'epic':ep,'a':a,'b':b})
  await test('beads-parent-a','beads','dep',{'issue_id':a,'depends_on_id':ep,'dep_type':'parent-child'})
  await test('beads-parent-b','beads','dep',{'issue_id':b,'depends_on_id':ep,'dep_type':'parent-child'})
  await test('beads-block','beads','dep',{'issue_id':b,'depends_on_id':a,'dep_type':'blocks'})
  await test('beads-cycle','beads','dep',{'issue_id':a,'depends_on_id':b,'dep_type':'blocks'},True)
  await test('beads-ready','beads','ready');await test('beads-blocked','beads','blocked');await test('beads-list','beads','list',{'limit':20})
  await test('beads-show','beads','show',{'issue_id':b});await test('beads-claim','beads','claim',{'issue_id':a})
  await test('beads-update','beads','update',{'issue_id':a,'notes':'Тест выполнен в независимой базе Hermes BN.'})
  await test('beads-comment','beads','comment',{'issue_id':a,'text':'Проверены синтетические данные, научные источники не читались.'})
  await test('beads-comments','beads','comments',{'issue_id':a});await test('beads-note','beads','note',{'issue_id':a,'text':'Дополнительная запись проверки.'})
  await test('beads-close-a','beads','close',{'issue_id':a,'reason':'Синтетическая проверка завершена.'});await test('beads-ready-after-close','beads','ready')
  await test('beads-close-b','beads','close',{'issue_id':b,'reason':'Синтетическая проверка завершена.'});await test('beads-reopen','beads','reopen',{'issue_ids':[b],'reason':'Проверка обратимого возобновления.'});await test('beads-reclose','beads','close',{'issue_id':b,'reason':'Проверка возобновления завершена.'})
  await test('beads-wrong-workspace','beads','stats',{'workspace_root':str(R/'workspace')},True)
  # Dolt versioning. Every operation names a working database/branch explicitly.
  scope=lambda branch='main':{'working_database':'knowledgework','working_branch':branch}
  branch='bn-local-check'
  await test('dolt-version','dolt','select_version');await test('dolt-tables','dolt','show_tables',scope());await test('dolt-describe','dolt','describe_table',{**scope(),'table':'research_records'});await test('dolt-schema','dolt','show_create_table',{**scope(),'table':'research_records'})
  await test('dolt-create-branch','dolt','create_dolt_branch',{'working_database':'knowledgework','original_branch':'main','new_branch':branch})
  await test('dolt-create-from-head','dolt','create_dolt_branch_from_head',{**scope(branch),'new_branch':'bn-head-check'})
  await test('dolt-create-table','dolt','create_table',{**scope(branch),'query':'CREATE TABLE synthetic_checks (id BIGINT PRIMARY KEY, value VARCHAR(200))'})
  await test('dolt-insert','dolt','exec',{**scope(branch),'query':"INSERT INTO synthetic_checks VALUES (1,'alpha'),(2,'beta')"})
  await test('dolt-query','dolt','query',{**scope(branch),'query':'SELECT * FROM synthetic_checks ORDER BY id'})
  await test('dolt-alter','dolt','alter_table',{**scope(branch),'query':'ALTER TABLE synthetic_checks ADD COLUMN note TEXT'})
  await test('dolt-stage-one','dolt','stage_table_for_dolt_commit',{**scope(branch),'table':'synthetic_checks'})
  await test('dolt-unstage-one','dolt','unstage_table',{**scope(branch),'table':'synthetic_checks'})
  await test('dolt-stage-all','dolt','stage_all_tables_for_dolt_commit',scope(branch));await test('dolt-unstage-all','dolt','unstage_all_tables',scope(branch));await test('dolt-restage','dolt','stage_all_tables_for_dolt_commit',scope(branch))
  await test('dolt-commit-a','dolt','create_dolt_commit',{**scope(branch),'message':'Synthetic connection check: initial rows'})
  await test('dolt-update','dolt','exec',{**scope(branch),'query':"UPDATE synthetic_checks SET value='beta updated' WHERE id=2"})
  await test('dolt-worktree-diff','dolt','list_dolt_diff_changes_in_working_set',scope(branch))
  await test('dolt-table-diff','dolt','list_dolt_diff_changes_by_table_name',{**scope(branch),'table':'synthetic_checks','from_commit':'HEAD','to_commit':'WORKING'})
  await test('dolt-stage-b','dolt','stage_all_tables_for_dolt_commit',scope(branch));await test('dolt-commit-b','dolt','create_dolt_commit',{**scope(branch),'message':'Synthetic connection check: changed one cell'})
  await test('dolt-history','dolt','list_dolt_commits',scope(branch));await test('dolt-active','dolt','select_active_branch',scope(branch));await test('dolt-branches','dolt','list_dolt_branches',{'working_database':'knowledgework'})
  await test('dolt-snapshot','dolt','query',{**scope(branch),'query':"SELECT id,value FROM synthetic_checks AS OF 'HEAD~1' ORDER BY id"})
  await test('dolt-test-add','dolt','add_dolt_test',{**scope(branch),'test_name':'synthetic_positive_count','query':'SELECT COUNT(*) FROM synthetic_checks','assertion_type':'expected_single_value','assertion_comparator':'==','assertion_value':'2','test_group':'connection'})
  await test('dolt-test-run','dolt','run_dolt_tests',{**scope(branch),'target':'connection'})
  await test('dolt-test-remove','dolt','remove_dolt_test',{**scope(branch),'test_name':'synthetic_positive_count'})
  await test('dolt-merge-status','dolt','get_dolt_merge_status',scope(branch));await test('dolt-remotes','dolt','list_dolt_remotes',scope(branch))
  await test('dolt-rename','dolt','move_dolt_branch',{**scope(branch),'old_name':'bn-head-check','new_name':'bn-head-renamed'})
  await test('dolt-date-diff','dolt','list_dolt_diff_changes_in_date_range',{**scope(branch),'start':'2026-01-01','end':'2027-01-01'})
  for suffix in ['merge','noff']:
   bname='bn-'+suffix+'-check'
   await test('dolt-branch-'+suffix,'dolt','create_dolt_branch',{'working_database':'knowledgework','original_branch':branch,'new_branch':bname})
   await test('dolt-write-'+suffix,'dolt','exec',{**scope(bname),'query':"INSERT INTO synthetic_checks (id,value) VALUES ("+('3' if suffix=='merge' else '4')+",'synthetic merge check')"})
   await test('dolt-stage-'+suffix,'dolt','stage_all_tables_for_dolt_commit',scope(bname))
   await test('dolt-commit-'+suffix,'dolt','create_dolt_commit',{**scope(bname),'message':'Synthetic '+suffix+' branch'})
   await test('dolt-merge-'+suffix,'dolt','merge_dolt_branch' if suffix=='merge' else 'merge_dolt_branch_no_fast_forward',{**scope(branch),'branch':bname,'message':'Synthetic merge verification'})
  await test('guard-wrong-database','dolt','query',{'working_database':'mysql','working_branch':'main','query':'SELECT 1'},True)
  await test('guard-drop-via-exec','dolt','exec',{**scope(branch),'query':'DROP DATABASE knowledgework'},True)
  await test('guard-multi-statement','dolt','query',{**scope(branch),'query':'SELECT 1; DROP DATABASE knowledgework'},True)
  await test('guard-file-read','dolt','query',{**scope(branch),'query':"SELECT LOAD_FILE('/etc/passwd')"},True)
  await test('guard-force','dolt','create_dolt_branch',{'working_database':'knowledgework','original_branch':'main','new_branch':branch,'force':True},True)
  await test('guard-rename-main','dolt','move_dolt_branch',{**scope(branch),'old_name':'main','new_name':'other-main'},True)
  # Two concurrent reads explicitly target different branches.
  responses=await asyncio.gather(clients['dolt'].call_tool('query',{**scope('main'),'query':'SELECT ACTIVE_BRANCH() AS branch'}),clients['dolt'].call_tool('query',{**scope(branch),'query':'SELECT ACTIVE_BRANCH() AS branch'}))
  assert all(not v.is_error for v in responses)
  dump(Z/'checks/concurrent-branch-isolation.json',{'results':[r.model_dump(mode='json',by_alias=True) for r in responses],'expected':['main',branch]})
  # Remaining tool argument schemas are stored for adaptive merge/rename checks.
  dump(Z/'checks/native-first-stage.json',{'test_branch':branch,'beads_epic':ep,'beads_a':a,'beads_b':b,'verified_tools':{kind:sorted({v['tool'] for v in proof.values() if v['server']==kind and not v['expected_error'] and v['passed']}) for kind in clients}})
  for kind in clients:
   covered={v['tool'] for v in proof.values() if v['server']==kind and not v['expected_error'] and v['passed']}
   assert covered==set(tools[kind]),(kind,set(tools[kind])-covered)
  dump(Z/'checks/native-method-coverage.json',{'beads':sorted(tools['beads']),'dolt':sorted(tools['dolt']),'count':len(tools['beads'])+len(tools['dolt']),'cases':len(proof),'all_passed':all(v['passed'] for v in proof.values())})
  print('NATIVE COMPLETE',len(proof),flush=True)
asyncio.run(main())
