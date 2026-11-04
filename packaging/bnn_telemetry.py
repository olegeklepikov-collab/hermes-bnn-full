"""Non-invasive BNN telemetry. Read-only inputs; private, bounded metadata outputs.

No bot input, model request, module switch, service restart, grant, source write,
or raw conversation/identity/credential export. Byte counts are never tokens.
"""
from pathlib import Path
import argparse,collections,datetime,fcntl,hashlib,json,math,os,re,signal,sqlite3,time

KNOWN={
 'research_projection_split_required_do_not_trim':'context_projection_bound',
 'CONTEXT_LIMIT':'module_context_closure_bound',
 'record_not_visible_to_analytical_role':'analytical_visibility_denied',
 'successful_completed_role_required':'dependent_role_not_completed',
 'intake_disabled_for_session':'intake_disabled',
 'intake_native_work_binding_required':'work_binding_missing',
 'current_turn_context_not_ready':'context_preparation_not_ready',
 'embedding_previous_outcome_unsettled_no_automatic_repeat':'unknown_embedding_outcome',
 'backend_operation_not_approved':'backend_admission_denied',
 'required_contract_exceeds_bound_split_work':'mandatory_context_bound',
 'required_contract_cycle':'mandatory_context_cycle',
 'required_contract_missing':'mandatory_context_missing',
 'no_new_input_or_progress':'search_no_progress',
 'finish_retry_requires_identical_report':'finish_retry_input_changed',
}
SAFE=re.compile(r'^[A-Za-z0-9_.:-]{1,140}$')
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def decode(value):
    if not isinstance(value,str):return value
    try:return json.loads(value)
    except (ValueError,TypeError):return None
def read_db(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise RuntimeError('existing_regular_database_required')
    c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN');return c
def atom(path,value):
    path=Path(path);temp=path.with_name(path.name+'.new')
    fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False);f.write('\n')
    os.replace(temp,path)
def classify(content):
    """Only known reason codes, never raw exception text or document contents."""
    text=content or '';value=decode(text)
    if text.strip()=='Your request was not processed. Send it again if you still want me to carry it out.':
        return [{'code':'request_not_processed','category':'execution_not_processed_reason_not_persisted'}]
    failed=isinstance(value,dict) and (value.get('error') not in (None,False,'') or value.get('ok') is False or value.get('isError') is True)
    payload=json.dumps(value.get('error'),ensure_ascii=False) if failed and isinstance(value,dict) else text if text.startswith(('Error executing tool','Execution blocked:','[TOOL_ERROR]')) else ''
    codes=[k for k in KNOWN if k in payload]
    if 'KeyError' in payload and 'run_id' in payload:codes.append('missing_run_id_after_failed_start')
    if not codes and payload:
        for phrase,code in [('execution controller','execution_controller_unavailable'),('context preparation','context_preparation_failed')]:
            if phrase in payload.lower():codes.append(code)
    if failed or payload:return [{'code':c,'category':KNOWN.get(c,'execution_failure')} for c in codes] or [{'code':'unclassified_tool_error','category':'execution_failure'}]
    if isinstance(value,dict) and isinstance(value.get('status'),str) and value['status'] in {'failed','blocked','unavailable','partial','needs'}:
        return [{'code':'returned_status_'+value['status'],'category':'explicit_incomplete_outcome'}]
    return []
def bounds(arguments):
    if not isinstance(arguments,dict):return {}
    result={}
    for k,v in arguments.items():
        if k in {'byte_limit','max_chars','max_tokens','max_context_chars','limit','page_size','max_candidates'} and type(v) in (int,float) and math.isfinite(v):result[k]=v
        elif k in {'profile','requested_profile'} and v in ['eMVP','MVP','Standard','eStandard','High Stakes','Critical Infrastructure']:result[k]=v
        elif k=='components' and v in ['G','S','D','GS','GD','SD','GSD']:result[k]=v
        elif k=='role' and v in ['parent','collector','analyst','reviewer','G','S','D','parser','computation']:result[k]=v
        elif k=='action' and v in ['start','status','pause','resume','refresh','recover_finish','plan','dispatch','complete_step','prepare','record','finish','read','search','bind','result','run','continue','profile_status']:result[k]=v
        elif k in {'procedure_ids','records','documents','source_ids'} and isinstance(v,list):result[k+'_count']=len(v)
    return result
def calls(raw):
    out=[]
    for call in decode(raw) or []:
        if not isinstance(call,dict):continue
        f=call.get('function',call);args=decode(f.get('arguments')) if isinstance(f.get('arguments'),str) else f.get('arguments',{})
        name=f.get('name','unknown')
        if isinstance(args,dict) and name=='tool_call':
            for item in args.get('calls',[]):
                if not isinstance(item,dict):continue
                a=item.get('arguments',item.get('args',{}));a=decode(a) if isinstance(a,str) else a
                n=item.get('name','unknown');out.append({'name':n if isinstance(n,str) and SAFE.fullmatch(n) else 'unknown','bounds':bounds(a)})
        else:out.append({'name':name if isinstance(name,str) and SAFE.fullmatch(name) else 'unknown','bounds':bounds(args)})
    return out

class Monitor:
    def __init__(self,root,state):
        self.root=Path(root).resolve();self.state=Path(state).resolve();self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.config=json.loads((self.root/'Memory/settings.json').read_text())
        self.cursor=decode((self.state/'cursor.json').read_text()) if (self.state/'cursor.json').exists() else {'message_id':None,'context_id':None,'log':{},'status_hashes':{}}
        self.stopped=False
    def emit(self,value):
        value={'event_id':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),'observed_at_utc':now(),**value};path=self.state/('events-'+time.strftime('%Y%m%d',time.gmtime())+'.jsonl')
        fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:f.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n')
    def messages(self):
        c=read_db(self.root/'data/state.db')
        try:
            maximum=c.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
            last=self.cursor.get('message_id')
            if last is None:last=max(0,maximum-500)
            if maximum<last:self.emit({'kind':'observation_gap','code':'native_message_sequence_rewound'});last=max(0,maximum-500)
            rows=c.execute('SELECT id,session_id,role,tool_name,content,tool_calls,finish_reason,timestamp FROM messages WHERE id>? ORDER BY id LIMIT 256',(last,)).fetchall()
            for row in rows:
                text=row['content'] or '';event={'kind':'native_message','message_id':row['id'],'sid':row['session_id'],'role':row['role'],'tool':row['tool_name'],'utf8_bytes':len(text.encode()),'finish_reason':row['finish_reason'],'source_timestamp':row['timestamp']}
                if row['role']=='assistant' and row['tool_calls']:event['calls']=calls(row['tool_calls'])
                if row['role'] in {'tool','assistant'}:event['failures']=classify(text)
                if row['finish_reason'] in {'length','max_tokens'}:event.setdefault('failures',[]).append({'code':'model_output_limit','category':'context_output_bound'})
                self.emit(event);self.cursor['message_id']=row['id']
            leases=[dict(r) for r in c.execute('SELECT conversation_id,acquired_at,expires_at FROM session_turn_leases')]
            return {'message_id':self.cursor.get('message_id',last),'message_backlog':max(0,maximum-(self.cursor.get('message_id') or last)),'active_turns':leases}
        finally:c.rollback();c.close()
    def primary(self,active):
        c=read_db(Path(self.config['state_root'])/'memory.sqlite')
        try:
            maximum=c.execute('SELECT COALESCE(MAX(rowid),0) FROM context_attempts').fetchone()[0];last=self.cursor.get('context_id')
            if last is None:last=max(0,maximum-100)
            for row in c.execute('SELECT rowid,sid,receipt FROM context_attempts WHERE rowid>? ORDER BY rowid LIMIT 256',(last,)).fetchall():
                r=decode(row['receipt']) or {};event={'kind':'context_request','rowid':row['rowid'],'sid':row['sid'],'request_bytes':r.get('request_bytes'),'provider_tokens':r.get('provider_tokens'),'status':r.get('status'),'model':r.get('request_model'),'effort':r.get('request_reasoning_effort'),'measurement':'request UTF-8 bytes; not model tokens'}
                self.emit(event);self.cursor['context_id']=row['rowid']
            status={}
            for table,field in [('model_attempts','state'),('module_attempts','state'),('document_pending','state'),('result_deliveries','state')]:
                columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                if field not in columns:field='status' if 'status' in columns else None
                if field:status[table]=[dict(r) for r in c.execute('SELECT '+field+',count(*) AS n FROM '+table+' GROUP BY '+field)]
            sessions=[];children=[]
            for sid in active:
                b=c.execute('SELECT profile_id,sid,project,task,parent,readonly,role,assignment_id FROM sessions WHERE sid=?',(sid,)).fetchone()
                if not b:continue
                p=c.execute('SELECT gsd_mode,research_enabled,revision FROM session_policy WHERE sid=?',(sid,)).fetchone()
                i=c.execute('SELECT mode,revision FROM intake_modes WHERE sid=? ORDER BY revision DESC LIMIT 1',(sid,)).fetchone()
                a=c.execute('SELECT status FROM context_admissions WHERE sid=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
                sessions.append({'binding':dict(b),'module_policy':dict(p) if p else None,'intake':dict(i) if i else {'mode':'off','source':'default_no_saved_mode'},'context_admission':a[0] if a else 'absent'})
                children.extend(dict(r) for r in c.execute('SELECT sid,parent,readonly,role,assignment_id FROM sessions WHERE parent=?',(sid,)))
            for table,rows in status.items():
                h=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
                if self.cursor['status_hashes'].get(table)!=h:
                    previous=self.cursor.setdefault('counts',{}).get(table);bad={'outcome_unknown','unknown','failed','blocked','needs','cancelled'};new=[]
                    if previous is not None:
                        old={r.get('state',r.get('status')):r['n'] for r in previous}
                        new=[{'state':r.get('state',r.get('status')),'increase':r['n']-old.get(r.get('state',r.get('status')),0)} for r in rows if r.get('state',r.get('status')) in bad and r['n']>old.get(r.get('state',r.get('status')),0)]
                    self.emit({'kind':'state_counts','table':table,'counts':rows,'baseline':previous is None,'new_failure_counts':new});self.cursor['status_hashes'][table]=h;self.cursor['counts'][table]=rows
            return {'active_session_policies':sessions,'child_bindings':children,'state_counts':status}
        finally:c.rollback();c.close()
    def logs(self):
        # The plugin dispatcher writes preparation timeouts to agent.log, whereas
        # the transcript can persist only a generic refusal. Observe both paths.
        seen=self.cursor.setdefault('log_fingerprints',[])
        for name in ['gateway.log','agent.log','errors.log','gateway.error.log']:
            self.log_file(self.root/'data/logs'/name,seen)
        self.cursor['log_fingerprints']=seen[-1024:]
    def log_file(self,path,seen):
        if not path.exists():return
        positions=self.cursor.setdefault('logs',{})
        st=path.stat();prior=positions.get(path.name) or (self.cursor.get('log') if path.name=='gateway.log' else {}) or {};offset=prior.get('offset',max(0,st.st_size-262144))
        if prior and (prior.get('inode')!=st.st_ino or st.st_size<offset):self.emit({'kind':'observation_gap','code':'gateway_log_rotated_or_truncated','source_log':path.name});offset=0
        with path.open('rb') as f:
            f.seek(offset);data=f.read(262144);end=data.rfind(b'\n')
            if end<0:return
            text=data[:end+1].decode('utf-8',errors='replace');position=offset+end+1
        for line in text.splitlines():
            if not re.search(r'\b(WARNING|ERROR|CRITICAL)\b|^(?:PermissionError|RuntimeError|TimeoutError|KeyError):',line):continue
            fingerprint=hashlib.sha256(line.encode()).hexdigest()
            if fingerprint in seen:continue
            seen.append(fingerprint)
            codes=[k for k in KNOWN if k in line]
            for phrase,code in [("Hook 'pre_llm_call'",'pre_llm_call_callback_timeout'),('Scoped index catch-up failed','secondary_index_catchup_failed'),('queued but not consumed','telegram_updates_pending_probe'),('Sticky Telegram path','telegram_sticky_path_failed'),('Dual-stack api.telegram.org path failed','telegram_hostname_path_failed'),('IPv4 Telegram API IP','telegram_ipv4_path_failed'),('Using sticky IPv4 Telegram API path','telegram_ipv4_path_selected')]:
                if phrase in line and (code!='pre_llm_call_callback_timeout' or 'timed out' in line):codes.append(code)
            level='ERROR' if any(k in line for k in ['ERROR','CRITICAL']) else 'WARNING'
            self.emit({'kind':'gateway_log_failure','source_log':path.name,'offset':offset,'severity':level,'codes':codes or ['unclassified_gateway_warning'],'line_fingerprint':fingerprint})
        positions[path.name]={'inode':st.st_ino,'offset':position}
    def poll(self):
        if os.statvfs(self.state).f_bavail*os.statvfs(self.state).f_frsize<64*1024*1024:raise RuntimeError('telemetry_low_disk_stop_own_collector')
        native=self.messages();primary=self.primary([r['conversation_id'] for r in native['active_turns']]);self.logs()
        g=decode((self.root/'data/gateway_state.json').read_text()) or {};pid=g.get('pid');alive=False
        if isinstance(pid,int):
            try:os.kill(pid,0);alive=True
            except ProcessLookupError:pass
        sample={'observed_at_utc':now(),'gateway':{'pid':pid,'pid_exists':alive,'state':g.get('gateway_state'),'heartbeat_at':g.get('updated_at'),'active_agents':g.get('active_agents')},**native,**primary,
                'context':{'factual_budget_bytes':self.config.get('context_bytes'),'automatic_semantic':self.config.get('semantic_context'),'current_context_tokens':None,'cumulative_tokens_are_not_current_context':True},
                'coverage':{'raw_content_exported':False,'all_hidden_failures_observable':False,'live_model_hooks_changed':False,'unlogged_object_id_on_permission_denial':'unavailable','new_provider_calls':0,'root_databases_read_only':True}}
        gateway_health=json.dumps({'pid_exists':alive,'state':g.get('gateway_state')},sort_keys=True)
        if self.cursor['status_hashes'].get('gateway_health')!=gateway_health:
            self.emit({'kind':'gateway_health','pid':pid,'pid_exists':alive,'state':g.get('gateway_state')});self.cursor['status_hashes']['gateway_health']=gateway_health
        atom(self.state/'latest.json',sample);atom(self.state/'cursor.json',self.cursor);return sample

def report(state,new_only=False):
    state=Path(state);latest=decode((state/'latest.json').read_text()) if (state/'latest.json').exists() else {}
    marker=decode((state/'report-cursor.json').read_text()) if (state/'report-cursor.json').exists() else {};positions=marker or {};failures=[]
    for path in sorted(state.glob('events-*.jsonl')):
        offset=positions.get(path.name,0) if new_only else 0
        with path.open('rb') as f:
            f.seek(offset)
            for line in f:
                e=decode(line.decode())
                if not e:continue
                if e.get('failures') or e.get('new_failure_counts') or e.get('kind') in {'gateway_log_failure','observation_gap','monitor_error'} or e.get('kind')=='gateway_health' and (not e.get('pid_exists') or e.get('state')!='running'):failures.append(e)
            positions[path.name]=f.tell()
    if new_only:atom(state/'report-cursor.json',positions)
    failures=list({e['event_id']:e for e in failures}.values())
    return {'latest':latest,'new_failures':failures,'collector_last_observed_at':latest.get('observed_at_utc'),'monitoring_is_not_semantic_acceptance':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['watch','once','report']);p.add_argument('--root',type=Path);p.add_argument('--state',type=Path,required=True);p.add_argument('--interval',type=float,default=15);p.add_argument('--new-only',action='store_true');v=p.parse_args()
    if v.action=='report':print(json.dumps(report(v.state,v.new_only),ensure_ascii=False));return
    if not v.root:p.error('--root required')
    m=Monitor(v.root,v.state)
    if v.action=='once':print(json.dumps(m.poll(),ensure_ascii=False));return
    if v.interval<5:p.error('interval must be at least 5 seconds')
    with (v.state/'watch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        atom(v.state/'watcher.json',{'pid':os.getpid(),'root':str(v.root.resolve()),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'started_at_utc':now()})
        def stop(*args):m.stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        while not m.stopped:
            try:m.poll()
            except Exception as e:m.emit({'kind':'monitor_error','code':type(e).__name__,'observation_complete':False})
            deadline=time.monotonic()+v.interval
            while not m.stopped and time.monotonic()<deadline:time.sleep(min(0.5,max(0,deadline-time.monotonic())))
if __name__=='__main__':main()
