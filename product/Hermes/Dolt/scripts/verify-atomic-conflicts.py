from pathlib import Path
import sys,json
Z=Path(__file__).resolve().parents[1];sys.path.insert(0,str(Z));from workspace_api import *
for b,value in [('bn-atomic-left','synthetic left'),('bn-atomic-right','synthetic right')]:
 with db(admin=True) as c:rows(c,'CALL DOLT_BRANCH(%s,%s)',(b,'bn-local-check'))
 with db(b) as c:
  rows(c,'UPDATE synthetic_checks SET value=%s WHERE id=1',(value,));rows(c,"CALL DOLT_ADD('.')");rows(c,"CALL DOLT_COMMIT('-m',%s)",('Synthetic atomic conflict '+b,))
preview=call('merge_preview',{'source_branch':'bn-atomic-right','target_branch':'bn-atomic-left'});dump(Z/'checks/atomic-conflict-preview.json',preview);assert preview['ok'],preview;assert preview['data_conflicts'] and 'synthetic_checks' in preview['conflict_rows'];assert preview['conflict_rows']['synthetic_checks'][0]['our_value']=='synthetic left';assert preview['conflict_rows']['synthetic_checks'][0]['their_value']=='synthetic right'
with db('bn-atomic-left') as c:
 assert not rows(c,'SELECT * FROM dolt_status');assert rows(c,'SELECT value FROM synthetic_checks WHERE id=1')[0]['value']=='synthetic left'
print('Preview detected actual conflict and rolled back',flush=True)
failed=call('merge_resolve',{'source_branch':'bn-atomic-right','target_branch':'bn-atomic-left','resolutions':[],'message':'Should roll back unresolved synthetic conflict'});assert not failed['ok'];dump(Z/'checks/atomic-conflict-unresolved.json',failed)
resolved=call('merge_resolve',{'source_branch':'bn-atomic-right','target_branch':'bn-atomic-left','resolutions':[{'table':'synthetic_checks','choice':'ours'}],'message':'Resolve synthetic check explicitly: preserve left value; no research claim'});dump(Z/'checks/atomic-conflict-resolution.json',resolved);assert resolved['ok'],resolved
with db('bn-atomic-left') as c:
 assert not rows(c,'SELECT * FROM dolt_status');assert not rows(c,'SELECT * FROM dolt_conflicts');assert rows(c,'SELECT value FROM synthetic_checks WHERE id=1')[0]['value']=='synthetic left';assert rows(c,'SELECT @@dolt_allow_commit_conflicts AS value')[0]['value']==0
print('Atomic conflict resolution verified; default conflict policy remains 0',flush=True)
for _ in range(30):
 ready=bd('ready')
 if not ready:break
 for issue in ready:
  assert 'Синтетическая' in issue['title'],issue
  bd('close',issue['id'],'--reason','Синтетическая проверка структуры и интерфейсов завершена; научное исследование не выполнялось.')
assert not bd('ready');print('Synthetic task graph closed in dependency order',flush=True)
print('backups refreshed',call('beads_backup')['ok'],call('dolt_backup')['ok'],flush=True)
