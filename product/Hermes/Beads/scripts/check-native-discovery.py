"""Test the native app's documented JSON-RPC backend without changing other profiles."""
import asyncio,json,re,sys
from pathlib import Path
from urllib.parse import urlencode
import psutil,requests,websockets
P=Path(__file__).resolve().parents[1];R=P.parent
async def main():
 candidates=[]
 for p in psutil.process_iter(['pid','cmdline']):
  c=p.info['cmdline'] or []
  if 'hermes_cli.main' in c and 'serve' in c and p.environ().get('HERMES_HOME')==str(R/'data'):candidates.append(p)
 assert len(candidates)==1, 'Need the single own desktop backend'
 proc=candidates[0];port=next(c.laddr.port for c in proc.net_connections(kind='inet') if c.status=='LISTEN' and c.laddr.ip=='127.0.0.1')
 token=proc.environ().get('HERMES_DASHBOARD_SESSION_TOKEN')
 if not token:
  r=requests.get(f'http://127.0.0.1:{port}/',timeout=20);r.raise_for_status();token=json.loads(re.search(r'__HERMES_SESSION_TOKEN__\s*=\s*("[^"\n]+")',r.text).group(1))
 events=[];path=P/'checks/native-discovery-session.json';counter=0
 def save():path.write_text(json.dumps(events,ensure_ascii=False,indent=2));path.chmod(0o600)
 async with websockets.connect(f'ws://127.0.0.1:{port}/api/ws?'+urlencode({'token':token}),max_size=10_000_000,proxy=None) as ws:
  async def rpc(method,params):
   nonlocal counter
   counter+=1;rid=counter;await ws.send(json.dumps({'jsonrpc':'2.0','id':rid,'method':method,'params':params}))
   while True:
    raw=await asyncio.wait_for(ws.recv(),timeout=180)
    for line in raw.splitlines():
     r=json.loads(line);events.append(r);save()
     if r.get('id')==rid:
      if 'error' in r:raise RuntimeError(str(r['error']))
      return r['result']
  reload=await rpc('reload.mcp',{'confirm':True});print('native_reload',reload.get('status'),flush=True)
  created=await rpc('session.create',{'cwd':str(R/'workspace')});sid=created['session_id'];print('native_session',sid,flush=True)
  answer=await rpc('prompt.submit',{'session_id':sid,'text':(P/'checks/native-query.txt').read_text()});print('prompt_accepted',bool(answer),flush=True)
  # Agent output is also durable in state.db; stop once the backend emits a terminal status.
  try:
   while True:
    raw=await asyncio.wait_for(ws.recv(),timeout=120)
    for line in raw.splitlines():
     r=json.loads(line);events.append(r);save()
     params=r.get('params',{});method=params.get('type','') if r.get('method')=='event' else r.get('method','')
     if method in {'agent.end','agent.done','turn.end','turn.done','prompt.done','turn.complete','turn.completed','message.complete'}:
      print('native_done',method,flush=True);return
  except asyncio.TimeoutError:
   print('native_events_saved; inspect durable session',sid,flush=True)
asyncio.run(main())
