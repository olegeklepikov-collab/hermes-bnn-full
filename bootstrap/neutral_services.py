"""Own local native services. No account login, model generation or source-state reuse."""
import argparse,json,os,secrets,signal,socket,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
from neutral_prepare import save,environment

def config(bundle):return json.loads((bundle/'Hermes/Memory/settings.json').read_text())
def service_env(bundle):
 root=bundle/'Hermes';env=environment(root);pkg=Path(config(bundle)['package_root']);env['PYTHONPATH']=os.pathsep.join([str(pkg),str(root/'hermes-agent')])
 env['DYLD_LIBRARY_PATH']=os.pathsep.join(str(p) for p in (bundle/'NativeEnvironment/opt/homebrew/Cellar').glob('*/*/lib'))
 return env

def prepare(bundle):
 root=bundle/'Hermes';state=root/'state/services';cfg=config(bundle);neo=state/'neo4j';conf=neo/'conf';conf.mkdir(parents=True,exist_ok=True)
 for name in ['data','logs','run','import','plugins']:(neo/name).mkdir(exist_ok=True)
 (conf/'neo4j.conf').write_text('\n'.join(['server.default_listen_address=127.0.0.1','server.bolt.listen_address=:65001','server.http.listen_address=:65004','server.https.enabled=false','dbms.security.auth_enabled=true','server.memory.heap.initial_size=128m','server.memory.heap.max_size=512m','server.memory.pagecache.size=128m',*[f'server.directories.{key}={neo/key}' for key in ['data','logs','run','import','plugins']]])+'\n')
 env=service_env(bundle);env.update(NEO4J_CONF=str(conf),JAVA_HOME=str(root/'UDR/software/java21.jdk/Contents/Home'))
 marker=neo/'initialized.json'
 if not marker.exists():
  p=subprocess.run([str(root/'UDR/software/neo4j-community-5.26.31/bin/neo4j-admin'),'dbms','set-initial-password',Path(cfg['neo4j_password_file']).read_text()],env=env,capture_output=True,text=True,timeout=90)
  if p.returncode:raise RuntimeError('fresh_neo4j_password_setup_failed')
  save(marker,{'fresh_local_authority':True,'no_source_data':True})
 from bn_memory.embedding_contract import space
 memory=state/'agentmemory'/space(cfg)['space_id'];memory.mkdir(parents=True,exist_ok=True)
 workers=[{'name':'iii-worker-manager','config':{'port':65002,'host':'127.0.0.1'}},{'name':'iii-http','config':{'port':65000,'host':'127.0.0.1','default_timeout':180000}},
  {'name':'iii-state','config':{'adapter':{'name':'kv','config':{'store_method':'file_based','file_path':str(memory/'state_store.db')}}}},
  {'name':'iii-queue','config':{'adapter':{'name':'builtin'}}},{'name':'iii-pubsub','config':{'adapter':{'name':'local'}}},{'name':'iii-cron','config':{'adapter':{'name':'kv'}}},
  {'name':'iii-stream','config':{'port':65003,'host':'127.0.0.1','adapter':{'name':'kv','config':{'store_method':'file_based','file_path':str(memory/'stream_store')}}}}]
 save(state/'iii-config.yaml',{'workers':workers})
 zotero=state/'zotero';profile=zotero/'profile';data=zotero/'data';profile.mkdir(parents=True,exist_ok=True);data.mkdir(exist_ok=True)
 prefs={'extensions.zotero.useDataDir':True,'extensions.zotero.dataDir':str(data),'extensions.zotero.httpServer.enabled':True,'extensions.zotero.httpServer.port':65030,'extensions.zotero.httpServer.localAPI.enabled':True,'extensions.zotero.sync.autoSync':False,'extensions.zotero.firstRun2':False,'extensions.zotero.sync.storage.enabled':False,'app.update.auto':False,'app.update.enabled':False,'browser.shell.checkDefaultBrowser':False}
 (profile/'user.js').write_text('\n'.join('user_pref('+json.dumps(k)+', '+json.dumps(v)+');' for k,v in prefs.items())+'\n')
 return memory

def start(bundle,no_gui=False):
 root=bundle/'Hermes';cfg=config(bundle);state=root/'state/services';env=service_env(bundle);sys.path.insert(0,cfg['package_root']);memory=prepare(bundle)
 for port in [65000,65001,65002,65003,65004,65006,65030]:
  with socket.socket() as s:
   if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('fresh_service_port_occupied:'+str(port))
 def spawn(name,argv,cwd,extra=None):
  with (state/(name+'.log')).open('ab') as log:p=subprocess.Popen(list(map(str,argv)),cwd=cwd,env={**env,**(extra or {})},stdout=log,stderr=log,start_new_session=True)
  save(state/(name+'.pid.json'),{'pid':p.pid,'root':str(root),'argv':list(map(str,argv))})
 if Path(cfg['voyage_key_file']).is_file():spawn('embedding',[root/'hermes-agent/venv/bin/python',bundle/'neutral_services.py','embedding-run'],root)
 spawn('iii',[root/'UDR/software/bin/iii','--no-update-check','--config',state/'iii-config.yaml'],state)
 spawn('neo4j',[root/'UDR/software/neo4j-community-5.26.31/bin/neo4j','console'],state,{'NEO4J_CONF':str(state/'neo4j/conf'),'JAVA_HOME':str(root/'UDR/software/java21.jdk/Contents/Home')})
 end=time.monotonic()+45
 for port in [65000,65001,65002]:
  while True:
   try:
    with socket.create_connection(('127.0.0.1',port),timeout=.3):break
   except OSError:
    if time.monotonic()>end:raise TimeoutError('local_service_not_ready:'+str(port))
    time.sleep(.2)
 extras={'BNN_AGENTMEMORY_DATA_DIR':str(memory),'III_ENGINE_URL':'ws://127.0.0.1:65002','III_REST_PORT':'65000','III_STREAM_PORT':'65003','BNN_VIEWER_PORT':'65006','AGENTMEMORY_SECRET':Path(cfg['agentmemory_key_file']).read_text(),'EMBEDDING_PROVIDER':'openai','OPENAI_API_KEY_FOR_LLM':'false','OPENAI_EMBEDDING_API_KEY':(root/'private/embedding-local.token').read_text(),'OPENAI_EMBEDDING_BASE_URL':'http://127.0.0.1:65005/v1','OPENAI_EMBEDDING_MODEL':'voyage-4-large','OPENAI_EMBEDDING_DIMENSIONS':'1024','AGENTMEMORY_ALLOW_AGENT_SDK':'false','AGENTMEMORY_AUTO_COMPRESS':'false','CLAUDE_MEMORY_BRIDGE':'false','AGENTMEMORY_CONSOLIDATION_ENABLED':'false'}
 spawn('agentmemory',[bundle/'NativeEnvironment/opt/homebrew/bin/node',cfg['agentmemory_adapter']],memory,extras)
 if not no_gui:spawn('zotero',[root/'Zotero/app/Zotero.app/Contents/MacOS/zotero','-no-remote','-profile',state/'zotero/profile'],state)
 return {'native_start_requested':True,'gui_requested':not no_gui,'embedding_gateway_started':Path(cfg['voyage_key_file']).is_file(),'model_execution_not_implied_by_local_start':True}

def embedding_run(bundle):
 from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
 cfg=config(bundle);sys.path.insert(0,cfg['package_root'])
 from bn_memory.broker import Broker
 from bn_memory.embedding_gateway import Gateway
 broker=Broker(cfg);sid='local-projection-service';broker.store.bind(sid);token=(bundle/'Hermes/private/embedding-local.token').read_text()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def reply(self,status,value):
   raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  def do_GET(self):self.reply(200,{'status':'ready','contract':2})
  def do_POST(self):
   if self.path!='/v1/embeddings' or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):self.reply(403,{'error':'denied'});return
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=262144:raise ValueError('transport_bound')
    value=json.loads(self.rfile.read(size));self.reply(200,Gateway(broker,sid,value.get('input_type'),'agentmemory').embed(value))
   except Exception as exc:self.reply(400,{'error':type(exc).__name__})
 ThreadingHTTPServer(('127.0.0.1',65005),Handler).serve_forever()

def check(bundle,no_gui=False):
 root=bundle/'Hermes';cfg=config(bundle);state=root/'state/services';results={};sys.path.insert(0,cfg['package_root'])
 env=service_env(bundle)
 for backend,python in [('agentmemory',cfg['python']),('graphiti',cfg['graph_python']),('zvec',cfg['zvec_python'])]:
  from bn_memory.embedding_contract import space
  req={'config':cfg,'backend':backend,'operation':'health','payload':{'space_id':space(cfg)['space_id']}};end=time.monotonic()+60
  while True:
   p=subprocess.run([python,str(Path(cfg['package_root'])/'bn_memory/workers.py')],input=json.dumps(req),text=True,capture_output=True,env=env,cwd=root,timeout=90)
   if p.returncode==0:results[backend]=json.loads(p.stdout);break
   if time.monotonic()>end:raise RuntimeError('fresh_native_health_failed:'+backend+':'+p.stdout[-1000:])
   time.sleep(.3)
 save(state/'native-core-health.json',results)
 if no_gui:
  results['zotero']={'status':'not_checked','reason':'operator_selected_no_gui'}
 else:
  end=time.monotonic()+60
  while True:
   try:
    with urlopen(Request('http://127.0.0.1:65030/api/users/0/items?limit=1&format=json',headers={'Zotero-API-Version':'3'}),timeout=5) as r:
     entries=json.load(r);assert entries==[];results['zotero']={'status':r.status,'empty_library':True,'sync_enabled':False,'server_id_present':bool(r.headers.get('Zotero-Server-ID'))}
    break
   except OSError:
    if time.monotonic()>end:raise
    time.sleep(.3)
 results.update(no_provider_calls=True,no_embeddings_claimed=True,no_previous_data_used=True)
 save(state/'native-health.json',results);return results

def stop(bundle):
 root=bundle/'Hermes';state=root/'state/services';stopped=[]
 for name in ['zotero','agentmemory','neo4j','iii','embedding']:
  marker=state/(name+'.pid.json')
  if not marker.exists():continue
  row=json.loads(marker.read_text());pid=row['pid'];p=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
  if not p.stdout.strip():continue
  if str(root) not in p.stdout and str(bundle/'NativeEnvironment') not in p.stdout:raise PermissionError('own_process_identity_changed:'+name)
  os.kill(pid,signal.SIGTERM);stopped.append(name)
  end=time.monotonic()+40
  while True:
   p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
   if not p.stdout.strip() or p.stdout.strip().startswith('Z'):break
   if time.monotonic()>end:raise TimeoutError('graceful_stop_pending:'+name)
   time.sleep(.2)
 return {'stopped_own_services':stopped,'forced_kill':False}

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['prepare','start','check','stop','embedding-run']);a.add_argument('--no-gui',action='store_true');a.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parent);v=a.parse_args();b=v.bundle.resolve();os.environ.update(service_env(b));action=embedding_run if v.action=='embedding-run' else globals()[v.action];print(json.dumps(action(b,no_gui=v.no_gui) if v.action in {"start","check"} else action(b),ensure_ascii=False,indent=2,default=str))
