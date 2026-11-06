"""Persistent per-owner/session MCP peers; one SDK enter/use/exit task per peer."""
import asyncio,threading
from bn_memory.store import canonical,sha
def mark_terminal(host,parent,child,state):
 if state not in {'SUCCEEDED','FAILED','CANCELLED','INTERRUPTED'}:return
 if not isinstance(child,str) or not child:return
 with host.store.db() as db:
  if not db.execute('SELECT 1 FROM sessions WHERE profile_id=? AND sid=?',(host.store.profile,child)).fetchone():return
 binding=host.store.binding(child)
 if not binding['readonly'] or binding['parent']!=parent:raise PermissionError('service_terminal_native_parent_mismatch')
 with host.store.db() as db:
  db.execute('CREATE TABLE IF NOT EXISTS service_terminal_sessions(profile_id TEXT,sid TEXT,parent TEXT,state TEXT,PRIMARY KEY(profile_id,sid))')
  db.execute('INSERT OR IGNORE INTO service_terminal_sessions VALUES(?,?,?,?)',(host.store.profile,child,parent,state))
class Pool:
 def __init__(self):
  self.ready=threading.Event();self.peers={};self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self._run,name='bnn-service-transports',daemon=True);self.thread.start();self.ready.wait(5)
 def _run(self):
  asyncio.set_event_loop(self.loop);self.ready.set();self.loop.run_forever()
 def request(self,config,entry,name,args,sid):
  return asyncio.run_coroutine_threadsafe(self._request(config,entry,name,args,sid),self.loop).result(timeout=entry.get('tool_timeout',180)+90)
 async def _request(self,config,entry,name,args,sid):
  import sqlite3
  from pathlib import Path
  with sqlite3.connect((Path(config['state_root'])/'memory.sqlite').as_uri()+'?mode=ro',uri=True) as db:
   table=db.execute("SELECT 1 FROM sqlite_master WHERE name='service_terminal_sessions'").fetchone()
   retired={r[0] for r in db.execute('SELECT sid FROM service_terminal_sessions WHERE profile_id=?',(config['namespace']['profile_id'],))} if table else set()
  if sid in retired:raise PermissionError('terminal_child_service_session_cannot_be_reopened')
  for key,peer in list(self.peers.items()):
   if peer['sid'] in retired:
    self.peers.pop(key);await peer['queue'].put(None)
  from bn_memory.service_engine import read_catalog
  declaration=read_catalog(config)['services'][entry['service']]['methods'][name]
  if declaration.get('api_request') or declaration.get('builtin'):
   from bn_memory.service_transport import call
   return await call(config,entry,name,args)
  policy_class='cran_metadata' if entry.get('untrusted_evaluator') and name.startswith('btw_tool_cran_') else 'default'
  entry=dict(entry);entry['_policy_method']=name
  key=sha(canonical([config['namespace'],sid,entry['service'],policy_class,config['service_integration']['registry_sha256'],config['service_integration']['catalogue_sha256']]))
  peer=self.peers.get(key)
  if peer is None:
   if len(self.peers)>=64:raise RuntimeError('service_transport_capacity_requires_closing_completed_sessions')
   queue=asyncio.Queue();ready=self.loop.create_future()
   from bn_memory.service_transport import call
   task=asyncio.create_task(call(config,entry,None,None,_queue=queue,_ready=ready));peer={'queue':queue,'ready':ready,'task':task,'sid':sid};self.peers[key]=peer
   def terminal(t):
    if not ready.done():
     error=t.exception() if not t.cancelled() else RuntimeError('service_peer_cancelled_before_ready')
     ready.set_exception(error or RuntimeError('service_peer_closed_before_ready'))
   task.add_done_callback(terminal)
  await asyncio.wait_for(asyncio.shield(peer['ready']),timeout=70)
  if peer['task'].done():raise RuntimeError('service_peer_closed_reconcile_before_reopening')
  result=self.loop.create_future();await peer['queue'].put((name,args,result,entry))
  try:return await asyncio.wait_for(result,timeout=entry.get('tool_timeout',180)+5)
  except TimeoutError:
   # A persistent interpreter may still be evaluating after the SDK request
   # timed out. Close this exact owned peer, not another session or gateway.
   self.peers.pop(key,None);peer['task'].cancel()
   await asyncio.gather(peer['task'],return_exceptions=True)
   raise TimeoutError('service_call_timed_out_owned_peer_closed_state_must_be_reloaded; prior operation outcome is not inferred') from None
 def close(self):
  async def stop():
   for p in self.peers.values():await p['queue'].put(None)
   tasks=[p['task'] for p in self.peers.values()]
   if tasks:
    try:await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=8)
    except asyncio.TimeoutError:
     for t in tasks:t.cancel()
     await asyncio.gather(*tasks,return_exceptions=True)
  if not self.loop.is_running():return
  try:asyncio.run_coroutine_threadsafe(stop(),self.loop).result(timeout=12)
  finally:self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(timeout=3)
