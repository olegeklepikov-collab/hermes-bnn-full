from pathlib import Path
import sys,json
Z=Path(__file__).resolve().parents[1];R=Z.parent;sys.path.insert(0,str(Z));from workspace_api import *
checks=json.loads((Z/'checks/workspace-verification.json').read_text())
for name,args in [('dolt_restore_copy',{'name':'connection-check'}),('read_documentation',{'tool':'beads','document':'docs/architecture/dolt.md','length':1200})]:
 res=call(name,args);checks[name]=res;dump(Z/'checks/workspace-verification.json',checks);print(name,res['ok'],res.get('error'),flush=True);assert res['ok'],res
source=R/'ASReview/exports/bn-telegram-check-44fe55aa.csv'
for name,args in [('memory_get',{'key':'missing-key'}),('import_records',{'file':str(source),'dataset_id':'bad','branch':'main','note':'test'}),('export_query',{'query':'DROP DATABASE knowledgework','branch':'main','name':'bad'}),('read_documentation',{'tool':'dolt','document':'../../config/credentials.json'})]:
 res=call(name,args);assert not res['ok'];checks['error-'+name]=res
coverage=sorted({v['operation'] for v in checks.values() if isinstance(v,dict) and v.get('ok')});assert set(coverage)==set(OPS);dump(Z/'checks/workspace-verification.json',checks);dump(Z/'checks/workspace-method-coverage.json',{'methods':coverage,'count':len(coverage),'branch':'bn-workspace-check','beads_epic':json.loads((B/'checks/test-issue-ids.json').read_text())['epic']});print('WORKSPACE COMPLETE',len(coverage),flush=True)
