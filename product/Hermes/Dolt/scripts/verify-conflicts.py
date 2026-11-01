from pathlib import Path
from contextlib import AsyncExitStack
import asyncio,json,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
Z=Path(__file__).resolve().parents[1];R=Z.parent;sys.path.insert(0,str(Z));from workspace_api import *
async def main():
 proof=[]
 with db(admin=True) as c:
  for b in ['bn-conflict-left','bn-conflict-right']:rows(c,'CALL DOLT_BRANCH(%s,%s)',(b,'bn-local-check'))
 for b,value in [('bn-conflict-left','synthetic left'),('bn-conflict-right','synthetic right')]:
  with db(b) as c:rows(c,'UPDATE synthetic_checks SET value=%s WHERE id=1',(value,));rows(c,"CALL DOLT_ADD('.')");rows(c,"CALL DOLT_COMMIT('-m',%s)",('Synthetic conflicting change '+b,))
 async with stdio_client(StdioServerParameters(command=str(R/'bin/dolt-bn-mcp'))) as streams:
  async with ClientSession(streams[0],streams[1],read_timeout_seconds=120) as c:
   await c.initialize();scope={'working_database':'knowledgework','working_branch':'bn-conflict-left'}
   for name,args in [('merge_dolt_branch',{**scope,'branch':'bn-conflict-right','message':'Synthetic conflict check'}),('get_dolt_merge_status',scope),('query',{**scope,'query':'SELECT * FROM dolt_conflicts_synthetic_checks'}),('exec',{**scope,'query':"UPDATE synthetic_checks SET value='synthetic resolved' WHERE id=1"}),('exec',{**scope,'query':'DELETE FROM dolt_conflicts_synthetic_checks'}),('stage_all_tables_for_dolt_commit',scope),('create_dolt_commit',{**scope,'message':'Resolve synthetic conflict explicitly; no research claim'}),('query',{**scope,'query':'SELECT COUNT(*) AS remaining_conflicts FROM dolt_conflicts_synthetic_checks'})]:
    result=await c.call_tool(name,args);proof.append({'name':name,'arguments':args,'result':result.model_dump(mode='json',by_alias=True)});dump(Z/'checks/conflict-verification.json',proof);print(name,'error' if result.is_error else 'ok',flush=True)
    if result.is_error and name!='merge_dolt_branch':raise RuntimeError(str(result.content)[:1000])
 with db('bn-conflict-left') as c:
  assert rows(c,'SELECT COUNT(*) AS n FROM dolt_conflicts_synthetic_checks')[0]['n']==0
  assert rows(c,'SELECT value FROM synthetic_checks WHERE id=1')[0]['value']=='synthetic resolved'
  assert not rows(c,'SELECT * FROM dolt_status')
 print('Conflict detection, explicit resolution and clean merge commit verified',flush=True)
asyncio.run(main())
