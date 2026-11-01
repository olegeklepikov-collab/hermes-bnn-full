from pathlib import Path
import sys,json,uuid,subprocess
Z=Path(__file__).resolve().parents[1];R=Z.parent;sys.path.insert(0,str(Z));from workspace_api import *
checks={};ids=json.loads((B/'checks/test-issue-ids.json').read_text());issue=ids['epic']
def test(key,name,args={}):
 v=call(name,args);checks[key]=v;dump(Z/'checks/workspace-verification.json',checks);print(key,v.get('ok'),v.get('error'),flush=True)
 if not v['ok']:raise RuntimeError(key+': '+str(v))
 return v
test('status','service_status');test('prime','beads_prime');test('search','beads_search',{'query':'Синтетическая','limit':10});test('remember','memory_set',{'key':'connection-test','content':'Синтетическая проверка: научные статьи не читались.','source':'Проверка интерфейсов Hermes BN','limitations':'Не научный вывод.'});test('recall','memory_get',{'key':'connection-test'});test('memories','memory_list');test('history','issue_history',{'issue_id':ids['a']});test('graph','issue_graph',{'issue_id':issue});test('provenance','provenance_record',{'issue_id':issue,'kind':'used','ref':'synthetic:beads-dolt-connection-check','ref_kind':'work-id','payload':'Проверка API, не научный источник.'});test('provenance-repeat','provenance_record',{'issue_id':issue,'kind':'used','ref':'synthetic:beads-dolt-connection-check','ref_kind':'work-id','payload':'Проверка API, не научный источник.'});test('provenance-read','provenance_list',{'issue_id':issue});test('templates','workflow_templates')
for name in workflow_templates()['templates']:
 result=bd('mol','pour',name,'--var','question=Синтетическая проверка структуры','--dry-run');checks['template-dry-'+name]=result;dump(Z/'checks/workspace-verification.json',checks)
test('workflow','workflow_create',{'template':'exploratory-research','question':'Синтетическая проверка графа; исследование не выполняется'});test('beads-export','beads_export');test('beads-backup','beads_backup');test('beads-restore','beads_restore_copy',{'name':'connection-check'})
branch='bn-workspace-check'
with db(admin=True) as c:rows(c,'CALL DOLT_BRANCH(%s,%s)',(branch,'main'))
source=R/'ASReview/exports/bn-telegram-check-44fe55aa.csv';assert source.is_file();test('import','import_records',{'file':str(source),'dataset_id':'asreview-synthetic-check','branch':branch,'note':'24 вымышленные записи ASReview, научных публикаций нет; пустые метки означают непросмотренное.'})
with db(branch) as c:assert rows(c,"SELECT COUNT(*) AS n FROM research_records WHERE dataset_id='asreview-synthetic-check'")[0]['n']==24
bad=call('link_task_data',{'issue_id':issue,'dataset_id':'asreview-synthetic-check','branch':branch});assert not bad['ok'];checks['link-before-commit-rejected']=bad
with db(branch) as c:rows(c,"CALL DOLT_ADD('.')");rows(c,"CALL DOLT_COMMIT('-m','Synthetic ASReview data imported with source hash')")
test('link','link_task_data',{'issue_id':issue,'dataset_id':'asreview-synthetic-check','branch':branch});test('export-query','export_query',{'query':"SELECT dataset_id,record_id,JSON_UNQUOTE(JSON_EXTRACT(payload,'$.included')) AS imported_label FROM research_records ORDER BY record_id",'branch':branch,'name':'synthetic-labels','limit':30})
# An uncommitted row verifies that native backup is more than a commit export.
with db(branch) as c:rows(c,"INSERT INTO research_records VALUES ('asreview-synthetic-check',999,%s)",(json.dumps({'synthetic':True,'note':'uncommitted backup verification row'}),))
test('dolt-backup','dolt_backup');test('dolt-restore','dolt_restore_copy',{'name':'connection-check'});test('docs','read_documentation',{'tool':'beads','document':'docs/architecture/dolt.md','length':1200})
# Preserve explicit limitations and check errors do not look successful.
for name,args in [('memory_get',{'key':'missing-key'}),('import_records',{'file':str(source),'dataset_id':'bad','branch':'main','note':'test'}),('export_query',{'query':'DROP DATABASE knowledgework','branch':'main','name':'bad'}),('read_documentation',{'tool':'dolt','document':'../../config/credentials.json'})]:
 res=call(name,args);assert not res['ok'];checks['error-'+name]=res
dump(Z/'checks/workspace-verification.json',checks);coverage=sorted({v['operation'] for v in checks.values() if isinstance(v,dict) and v.get('ok')});assert set(coverage)==set(OPS);dump(Z/'checks/workspace-method-coverage.json',{'methods':coverage,'count':len(coverage),'branch':branch,'beads_epic':issue});print('WORKSPACE COMPLETE',len(coverage),flush=True)
