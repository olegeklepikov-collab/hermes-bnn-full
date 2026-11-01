"""Optional edge to the preserved GSD engine and native role implementation."""
import contextvars,json,re
from types import SimpleNamespace
_call=contextvars.ContextVar('bnn_gsd_call',default=None)

class Lifecycle:
    def __init__(self,adapter):self.adapter=adapter
    @property
    def service(self):return self.adapter.host.ctx.subagent_lifecycle
    def launch(self,request):
        host=self.adapter.host;current=_call.get()
        if not current:raise PermissionError('GSD_root_operation_required')
        sid,turn,arguments=current;match=re.match(r'^GSD_NATIVE_JOB:(J\.[a-f0-9]{32})\n',request.goal)
        if not match:raise PermissionError('canonical_GSD_job_required')
        job=self.adapter.runtime.bridge.call('job_get',{'job_id':match.group(1)})
        if job['parent_session_id']!=sid:raise PermissionError('GSD_job_parent_mismatch')
        resources=(arguments.get('assigned_resources') or {}).get(job['role'],{});resources={k:list(v) for k,v in resources.items()};permissions=[];corpus=arguments.get('corpus_id')
        proof_required=arguments.get('require_compute_proof') is True
        own_compute=proof_required and job['role'] in {'S','D'} and (job['role']=='S' or 'S' not in arguments.get('components','GSD'))
        if own_compute:permissions.append({'rule_id':'memory.compute.isolated','arguments_schema':{'type':'object','properties':{'action':{'enum':['run','read','status']}},'required':['action']}})
        if corpus:
            docs=host.document_store();docs.corpus(sid,corpus)
            if 'documents' not in resources:
                with host.store.db() as db:resources['documents']=[r[0] for r in db.execute('SELECT id FROM document_sources WHERE corpus=?',(corpus,))]
            if not resources.get('documents'):raise PermissionError('GSD_corpus_no_assigned_documents')
            if any(not docs.membership(sid,corpus,did) for did in resources['documents']):raise PermissionError('GSD_document_outside_declared_corpus')
        if resources.get('documents'):
            for name in ['document_read','document_status','document_describe']:
                permissions.append({'rule_id':'w2.'+name,'arguments_schema':{'type':'object'}})
        for kind,name in [('files','memory_files'),('code','memory_code'),('library','memory_library'),('data','memory_data')]:
            if resources.get(kind):permissions.append({'rule_id':'w3.child.'+name,'arguments_schema':{'type':'object'}})
        if resources.get('records'):
            permissions.extend([{'rule_id':'memory.read.record.child','arguments_schema':{'type':'object'}},
                {'rule_id':'memory.recall.cached.child','arguments_schema':{'type':'object'}}])
        if resources or own_compute:permissions += [{'rule_id':name,'arguments_schema':{'type':'object'}} for name in ['memory.recovery','memory.working.child','w3.discovery.describe','w3.discovery.search']]
        goal=request.goal
        if resources.get('documents'):
            goal+='\nRequired before completing this role: use document_describe and document_read to read every unit and complete fragment of ALL assigned document IDs in BN_ASSIGNED_RESOURCES. Use the assigned corpus_id, exact doc_id and this analytical phase. Extraction/index metadata is not reading. Do not rely on a parent summary. If unavailable return the explicit need; do not claim completed evidence.\n'
        if resources and not corpus:goal=goal.replace('Do not run tools, delegate,','Use only the host-assigned read-only tools when needed. Do not delegate,')
        from bn_memory.launch_admission import launch
        handle=launch(host,self.service,parent_sid=sid,turn_id=turn,goal=goal,analytical_role=job['role'],purpose=job['operation'],module='gsd',
            allowed_toolsets=('context',) if resources or own_compute else request.allowed_toolsets,tool_permissions=permissions,resources=resources,correlation_id=host.store.profile+'.'+job['id'],model='gpt-6.1-sol',provider='openai-codex')
        host.modules.track(job['id'],sid,'gsd',self.service,handle)
        return handle
    def computation_proofs(self,job_id):
        from bn_memory.gsd_compute_proofs import collect
        return collect(self.adapter,job_id)
    def wait(self,*a,**kw):return self.service.wait(*a,**kw)
    def result(self,handle):
        result=self.service.result(handle)
        if result.terminal_state.value=='SUCCEEDED':
            host=self.adapter.host
            identifier=next((key for key,value in host.modules.active.items() if value[3]==handle),None)
            if identifier:
                job=self.adapter.runtime.bridge.call('job_get',{'job_id':identifier});child=job['child_session_id']
                from bn_memory.assignment_resources import read
                selected=read(host.store,host.store.binding(child))['documents'];checks=[]
                for corpus in {row['corpus'] for row in selected.values()}:
                    checks.append(host.document_store().status(child,{'corpus_id':corpus,'_recipient_sid':child,'_phases':[job['role']]}))
                if any(not item['phases'][job['role']]['complete'] for item in checks):
                    import dataclasses
                    from bn_memory.store import canonical
                    actual=dataclasses.asdict(result);actual['handle'].pop('capability',None)
                    with host.store.db() as db:
                        db.execute('CREATE TABLE IF NOT EXISTS gsd_read_refusals(profile_id TEXT,job_id TEXT,body TEXT,PRIMARY KEY(profile_id,job_id))')
                        db.execute('INSERT OR REPLACE INTO gsd_read_refusals VALUES(?,?,?)',(host.store.profile,identifier,canonical({'actual_native_receipt':actual,'coverage':checks,'reason':'assigned_document_reception_incomplete'})))
                    raise PermissionError('GSD_assigned_document_reception_incomplete')
        if result.terminal_state.value in {'SUCCEEDED','FAILED','CANCELLED','INTERRUPTED'}:
            for identifier,row in list(self.adapter.host.modules.active.items()):
                if row[3]==handle:self.adapter.host.modules.active.pop(identifier,None)
        return result
    def cancel(self,*a,**kw):return self.service.cancel(*a,**kw)

class GSD:
    def __init__(self,host):
        self.host=host
        config=host.config['modules']['gsd']
        import sys
        sys.path.insert(0,config['host_package'])
        from bn_gsd.runtime import Runtime
        self.runtime=Runtime(SimpleNamespace(subagent_lifecycle=Lifecycle(self)),config['settings_file'])
    def child(self,sid):
        binding=self.host.store.binding(sid)
        if not binding['readonly'] or binding['role'] not in {'G','S','D'}:return False
        with self.host.store.db() as db:row=db.execute('SELECT module FROM launch_grants WHERE profile_id=? AND id=?',(self.host.store.profile,binding['assignment_id'])).fetchone()
        return bool(row and row[0]=='gsd')
    def bind_child(self,parent,child,goal):
        self.host.modules.require(parent,'gsd')
        return self.runtime.child_start(parent_session_id=parent,child_session_id=child,child_goal=goal)
    def call(self,sid,turn,name,args):
        self.host.store.writable(sid);self.host.admission.ready(sid,turn);self.host.modules.require(sid,'gsd')
        if name in {'gsd_research','gsd_analyze','gsd_work'}:
            try:card,_=self.host.working._card(sid)
            except PermissionError:return {'ok':False,'status':'needs_data','error':{'code':'PRIMARY_TASK_BINDING_REQUIRED','message':'Create/choose a primary Beads task, then memory_working bind before analytical execution.'},'native_jobs_started':0}
            bead=json.loads(card['primary_ref'])['id']
        else:bead=''
        self.runtime.bound_state(sid,'cli')
        identifier=None
        if args.get('request_id'):
            from bn_memory.store import canonical,sha
            identifier='GSD-'+sha(canonical([self.host.store.profile,sid,name,args['request_id']]))[:24];fingerprint=sha(canonical(args))
            with self.host.store.db() as db:
                db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM module_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,identifier)).fetchone()
                if old:
                    if old['input_hash']!=fingerprint:raise ValueError('GSD_request_id_input_conflict')
                    if old['state']!='succeeded':raise PermissionError('GSD_previous_attempt_requires_reconciliation')
                    return {'duplicate':True,'saved_result':json.loads(old['body']),'new_model_calls':0}
                db.execute('INSERT INTO module_attempts VALUES(?,?,?,?,?,?,?,?)',(self.host.store.profile,sid,identifier,'gsd',bead,fingerprint,'running','{}'))
        token=_call.set((sid,turn,args))
        try:
            clean={k:v for k,v in args.items() if k!='assigned_resources'}
            if name=='gsd_research':result=self.runtime.research(clean,sid)
            elif name=='gsd_analyze':result=self.runtime.analyze(clean,sid)
            elif name=='gsd_work':result=self.runtime.work(clean,sid)
            elif name=='gsd_read_role':result=self.runtime.read_role(args,sid)
            elif name=='gsd_runtime_status':result=self.runtime.bridge.call('family_status',{'sid':sid})
            else:result=self.runtime.bridge.engine(name,args,sid=sid)
            if identifier:
                with self.host.store.db() as db:db.execute('UPDATE module_attempts SET state=?,body=? WHERE profile_id=? AND id=?',('succeeded' if result.get('ok',True) else 'blocked',canonical(result),self.host.store.profile,identifier))
            return result
        except BaseException as exc:
            if identifier:
                with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='unknown',body=? WHERE profile_id=? AND id=?",(json.dumps({'error_class':type(exc).__name__}),self.host.store.profile,identifier))
            raise
        finally:_call.reset(token)

def get(host):
    if not hasattr(host,'_gsd_module'):host._gsd_module=GSD(host)
    return host._gsd_module

def is_child(host,sid):
    if not host.config.get('w3_enabled'):return False
    binding=host.store.binding(sid)
    if not binding['readonly'] or binding['role'] not in {'G','S','D'}:return False
    with host.store.db() as db:row=db.execute('SELECT module FROM launch_grants WHERE profile_id=? AND id=?',(host.store.profile,binding['assignment_id'])).fetchone()
    return bool(row and row[0]=='gsd')
