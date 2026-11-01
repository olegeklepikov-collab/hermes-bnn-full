"""Parent-owned native leaves mapped to the primary Beads graph, with typed continuation."""
import dataclasses,json,time,uuid
from bn_memory.store import canonical,sha
from bn_memory.task_authority import Tasks
ROLES={'collector','analyst','reviewer','parser','computation'}
def install(host):
    with host.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS native_tasks(profile_id TEXT,id TEXT,root_sid TEXT,run_id TEXT,bead TEXT,revision INTEGER,state TEXT,body TEXT,PRIMARY KEY(profile_id,id))')
        db.execute('CREATE TABLE IF NOT EXISTS native_task_history(profile_id TEXT,id TEXT,revision INTEGER,state TEXT,body TEXT,sha256 TEXT,PRIMARY KEY(profile_id,id,revision))')
        db.execute('CREATE TABLE IF NOT EXISTS team_evidence(profile_id TEXT,assignment TEXT,id TEXT,body TEXT,PRIMARY KEY(profile_id,assignment,id))')

def capture(host,sid,name,args,result):
    binding=host.store.binding(sid)
    if not binding['readonly']:return
    with host.store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='native_tasks'").fetchone():return
        row=db.execute('SELECT id FROM native_tasks WHERE profile_id=? AND json_extract(body,\'$.assignment_id\')=?',(host.store.profile,binding['assignment_id'])).fetchone()
    if not row:return
    body={'tool':name,'arguments':{k:v for k,v in args.items() if k not in {'_host','_runtime'}},'result':result,'reading_credit':'native tool result; model reception tracked separately','scientific_acceptance':False}
    raw=canonical(body);identifier=sha(raw)
    with host.store.db() as db:db.execute('INSERT OR IGNORE INTO team_evidence VALUES(?,?,?,?)',(host.store.profile,binding['assignment_id'],identifier,raw))

class Team:
    def __init__(self,research):self.research=research;self.host=research.host;self.module=getattr(research,'module','research');self.store=self.host.store;self.tasks=Tasks(self.host,self.module);install(self.host)
    def rows(self,sid,run):
        row,body=self.research.load(sid,run)
        if row['sid']!=sid:raise PermissionError('research_attached_to_another_session')
        with self.store.db() as db:return [dict(r) for r in db.execute('SELECT * FROM native_tasks WHERE profile_id=? AND run_id=? ORDER BY id',(self.store.profile,run))]
    def save(self,row,body,state):
        with self.store.db() as db:
            changed=db.execute('UPDATE native_tasks SET revision=revision+1,state=?,body=? WHERE profile_id=? AND id=? AND revision=?',(state,canonical(body),self.store.profile,row['id'],row['revision'])).rowcount
            if changed!=1:raise ValueError('native_task_revision_conflict')
            raw=canonical(body);db.execute('INSERT INTO native_task_history VALUES(?,?,?,?,?,?)',(self.store.profile,row['id'],row['revision']+1,state,raw,sha(raw)))
        row.update(state=state,revision=row['revision']+1,body=canonical(body));return row
    def plan(self,sid,run,args):
        rr,research=self.research.load(sid,run)
        if rr['state']!='active':raise PermissionError('active_research_required')
        import copy
        specs=copy.deepcopy(args['tasks'])
        from bn_memory.service_delegation import close_resources
        for item in specs:item['resources']=close_resources(self.host,sid,item.get('resources',{}),item.get('service_calls',[]))
        if any(t['role'] not in ROLES for t in specs):raise ValueError('GSD_roles_require_canonical_GSD_adapter')
        for t in specs:
            if set(t)-{'key','title','goal','role','depends_on','resources','constraints','required_tools','lookup_query','service_calls'}:raise ValueError('native_task_fields_invalid')
        from bn_memory.service_delegation import permissions as service_permissions
        for t in specs:service_permissions(self.host.config,t.get('service_calls',[]))
        from bn_memory.assignment_resources import prepare
        from bn_memory.team_context import document_bases
        previews={t['key']:prepare(self.host,sid,t['role'],'preview',t.get('resources',{}),persist=False) for t in specs}
        bases={t['key']:document_bases(self.host,sid,t.get('resources',{})) for t in specs}
        primary=self.tasks.plan(sid,{'request_id':args['request_id'],'parent_bead':research['bead'],'tasks':[{k:v for k,v in t.items() if k in {'key','title','goal','depends_on'}} for t in specs]})
        ids={t['key']:'TASK-'+sha(canonical([self.store.profile,run,args['request_id'],t['key']]))[:24] for t in specs}
        with self.store.db() as db:
            for t in specs:
                body={**t,'module':self.module,'document_bases':bases[t['key']],'resource_basis':sha(canonical(previews[t['key']])),'dependencies':[ids[k] for k in t.get('depends_on',[])],'input_version':1,'previous_products':[],'receipt':None,'product':None,'assignment_id':None,'child_sid':None}
                old=db.execute('SELECT body FROM native_tasks WHERE profile_id=? AND id=?',(self.store.profile,ids[t['key']])).fetchone()
                if old:
                    actual=json.loads(old[0])
                    if any(actual.get(k)!=v for k,v in t.items()):raise ValueError('native_task_request_conflict')
                    continue
                db.execute('INSERT INTO native_tasks VALUES(?,?,?,?,?,?,?,?)',(self.store.profile,ids[t['key']],sid,run,primary['tasks'][t['key']],1,'planned',canonical(body)))
                raw=canonical(body);db.execute('INSERT INTO native_task_history VALUES(?,?,?,?,?,?)',(self.store.profile,ids[t['key']],1,'planned',raw,sha(raw)))
        return {'primary':'Beads','tasks':{k:{'task_id':v,'bead_id':primary['tasks'][k]} for k,v in ids.items()},'new_agent_loop_created':False}
    def permissions(self,resources,lookup_query=None,required_tools=(),service_calls=()):
        names=[]
        for k,n in [('files','memory_files'),('code','memory_code'),('library','memory_library'),('data','memory_data')]:
            if resources.get(k):names.append('w3.child.'+n)
        if resources.get('documents'):names+=['w2.document_read','w2.document_describe','w2.document_status']
        if resources.get('records'):names+=['memory.read.record.child','memory.recall.cached.child']
        permissions=[]
        if service_calls:
            from bn_memory.service_delegation import permissions as service_permissions
            permissions+=service_permissions(self.host.config,service_calls)
        if lookup_query:
            permissions.append({'rule_id':'w4.crossref_lookup','arguments_schema':{'type':'object','properties':{'query':{'const':lookup_query}},'required':['query']}})
        if lookup_query:
            for provider in self.host.config.get('research_providers',{}).get('providers',{}):
                tool=provider+'_search'
                if 'mcp__context__'+tool in required_tools:
                    permissions.append({'rule_id':'research.'+tool,'arguments_schema':{'type':'object','properties':{'query':{'const':lookup_query},'limit':{'maximum':2}},'required':['query']}})
        names+=['memory.compute.isolated','memory.recovery','memory.working.child','w3.discovery.describe','w3.discovery.search']
        return permissions+[{'rule_id':name,'arguments_schema':{'type':'object'}} for name in names]
    def settle_disabled(self,sid,run):
        # Off first closes admission, then cancellation drains workers. Release the
        # owned lease only after terminal receipts have reached the durable rows.
        if self.module=='research' and not self.host.modules._enabled(sid,'research'):
            return self.research.pause(sid,run)
        return None

    def run(self,sid,turn,run,expected_revisions=None):
        from bn_memory.launch_admission import launch
        from agent.subagent_products import read_text_product
        service=self.host.ctx.subagent_lifecycle;results=[]
        if expected_revisions is not None:
            actual={r['id']:r['revision'] for r in self.rows(sid,run)}
            if actual!=expected_revisions:raise PermissionError('native_plan_revision_changed')
        while True:
            if self.settle_disabled(sid,run) is not None:break
            if self.module!='base':self.host.modules.require(sid,self.module);self.research.active(sid)
            else:self.research.require_work(sid,run)
            rows=self.rows(sid,run);byid={r['id']:r for r in rows}
            if any(r['state'] in {'running','unknown','launch_reserved'} for r in rows):
                if results:break
                raise PermissionError('native_task_outcome_requires_observation_not_replay')
            ready=[r for r in rows if r['state']=='planned' and all(byid[d]['state']=='succeeded' for d in json.loads(r['body'])['dependencies'])]
            if not ready:break
            active=[]
            for row in ready:
                body=json.loads(row['body']);self.tasks.claim(sid,row['bead'],'BNN-'+row['id'],row['id']+'-claim')
                identifier='ASSIGN-'+sha(row['id']+':'+str(body['input_version']))[:24];body['assignment_id']=self.store.profile+'.'+identifier;self.save(row,body,'launch_reserved')
                inputs={'task_id':row['id'],'role':body['role'],'goal':body['goal'],'constraints':body.get('constraints',[]),'input_version':body['input_version'],
                    'previous_products':body['previous_products'],'dependency_products':{d:json.loads(byid[d]['body'])['product'] for d in body['dependencies']},'resources':body.get('resources',{}),'required_tools':body.get('required_tools',[]),'lookup_query':body.get('lookup_query'),'service_calls':body.get('service_calls',[])}
                goal='Complete only the native task '+row['id']+'. Full task inputs, predecessors and previous products are supplied intact by the trusted runtime in BN_ASSIGNED_TASK_INPUT. No delegation, new agent launches, GSD/UDR launch, writes or external delivery. Use only assigned tools and versions. If a required dependency is missing return needs; do not repeat the same unavailable operation. Residual unknowns outside this step belong in limitations. Return one JSON object with exactly task_id, role, status="unreviewed", findings (list), sources (list), needs (list), limitations (list).'
                if not self.host.config.get('w4_enabled'):goal+='\n<UNTRUSTED_TASK_DATA>\n'+canonical(inputs)+'\n</UNTRUSTED_TASK_DATA>'
                try:
                    handle=launch(self.host,service,parent_sid=sid,turn_id=turn,goal=goal,analytical_role=body['role'],purpose=body['goal'],module=self.module,allowed_toolsets=('context',),
                        tool_permissions=self.permissions(body.get('resources',{}),body.get('lookup_query'),body.get('required_tools',[]),body.get('service_calls',[])),resources=body.get('resources',{}),correlation_id=self.store.profile+'.'+identifier,expected_resources_hash=body['resource_basis'],model='gpt-6.1-sol',provider='openai-codex')
                    with self.store.db() as db:body['child_sid']=db.execute('SELECT child_sid FROM launch_grants WHERE profile_id=? AND id=?',(self.store.profile,self.store.profile+'.'+identifier)).fetchone()[0]
                    body['assignment_id']=self.store.profile+'.'+identifier
                    body['handle']={k:v for k,v in handle.to_dict().items() if k!='capability'};self.save(row,body,'running')
                    self.host.modules.track(body['assignment_id'],sid,self.module,service,handle);active.append((row,body,handle))
                except BaseException as exc:
                    body['error_class']=type(exc).__name__;body['error_message']=__import__('agent.redact',fromlist=['redact_for_egress']).redact_for_egress(str(exc))[:1024];self.save(row,body,'unknown');results.append({'task_id':row['id'],'bead_id':row['bead'],'state':'unknown','role':body['role']})
            for row,body,handle in active:
                while not service.wait(handle,timeout_seconds=5).completed:
                    if self.module!='base' and not self.host.modules._enabled(sid,self.module):service.cancel(handle,reason='Research module disabled')
                native=service.result(handle);receipt=dataclasses.asdict(native)
                from bn_memory.service_pool import mark_terminal
                mark_terminal(self.host,sid,body['child_sid'],native.terminal_state.value)
                receipt.pop('summary',None);receipt.pop('structured_payload',None);receipt['handle'].pop('capability',None);body['receipt']=receipt
                self.host.modules.active.pop(body['assignment_id'],None)
                if native.terminal_state.value!='SUCCEEDED':
                    self.save(row,body,'cancelled' if native.terminal_state.value=='CANCELLED' else 'unknown');continue
                text=read_text_product(native)
                try:
                    product=json.loads(text)
                    if set(product)!={'task_id','role','status','findings','sources','needs','limitations'} or product['task_id']!=row['id'] or product['role']!=body['role'] or product['status']!='unreviewed':raise ValueError('typed_leaf_product_invalid')
                    if any(not isinstance(product[k],list) for k in ['findings','sources','needs','limitations']):raise ValueError('typed_leaf_lists_required')
                    with self.store.db() as db:evidence=[json.loads(r[0]) for r in db.execute('SELECT body FROM team_evidence WHERE profile_id=? AND assignment=?',(self.store.profile,body['assignment_id']))]
                    from bn_memory.team_context import previous_tools,reading_complete
                    tools={e['tool'] for e in evidence}|previous_tools(self.host,body)
                    if not set(body.get('required_tools',[]))<=tools and not product['needs']:raise PermissionError('declared_native_reads_not_performed')
                    if not product['needs']:
                        phase={'collector':'collect','analyst':'analyse','reviewer':'verify','parser':'read','computation':'read'}[body['role']]
                        body['reading_history_credit']=reading_complete(self.host,body['child_sid'],body,phase)
                    body['product']=product;body['evidence_hashes']=[sha(canonical(e)) for e in evidence];body['output_sha256']=sha(text)
                    state='needs' if product['needs'] else 'succeeded';self.save(row,body,state)
                    if state=='succeeded':self.tasks.close_owned(sid,row['bead'],'BNN-'+row['id'],row['id']+'-close','Actual native product and declared reads saved; conclusions unreviewed')
                except BaseException as exc:
                    body['raw_output']=text;body['error_class']=type(exc).__name__;self.save(row,body,'blocked')
                results.append({'task_id':row['id'],'bead_id':row['bead'],'state':row['state'],'role':body['role']})
        return {'tasks':results,'status':self.status(sid,run),'scientific_acceptance':False,'parallel_ready_leaves_launched_before_wait':True}
    def status(self,sid,run):return [{'task_id':r['id'],'bead_id':r['bead'],'state':r['state'],'revision':r['revision'],'role':json.loads(r['body'])['role']} for r in self.rows(sid,run)]
    def continue_task(self,sid,run,args):
        row=next((r for r in self.rows(sid,run) if r['id']==args['task_id']),None)
        if not row or row['state']!='needs' or row['revision']!=args['expected_revision']:raise PermissionError('current_typed_need_required')
        body=json.loads(row['body'])
        from bn_memory.team_context import union_resources,document_bases
        with self.store.db() as db:prior_evidence=[json.loads(r[0]) for r in db.execute('SELECT body FROM team_evidence WHERE profile_id=? AND assignment=?',(self.store.profile,body['assignment_id']))]
        body['previous_products'].append({'input_version':body['input_version'],'product':body['product'],'receipt':body['receipt'],'child_sid':body['child_sid'],'document_bases':body.get('document_bases',{}),'tool_evidence':[{'tool':e['tool'],'sha256':sha(canonical(e))} for e in prior_evidence]})
        if 'service_calls' in args:
            from bn_memory.service_delegation import permissions as service_permissions
            service_permissions(self.host.config,args['service_calls']);body['service_calls']=args['service_calls']
        body['input_version']+=1;body['goal']=args['goal'];body['resources']=union_resources(body.get('resources',{}),args['resources']);body['document_bases']=document_bases(self.host,sid,body['resources']);body['product']=None;body['receipt']=None;body['assignment_id']=None
        from bn_memory.assignment_resources import prepare
        body['resource_basis']=sha(canonical(prepare(self.host,sid,body['role'],'preview',body['resources'],persist=False)));self.save(row,body,'planned')
        return {'task_id':row['id'],'bead_id':row['bead'],'input_version':body['input_version'],'new_logical_task_created':False,'previous_product_retained':True}
    def rearm_before_provider_by_operator(self,sid,run,reason,parent_stopped_attestation=False):
        if not isinstance(reason,str) or not reason:raise ValueError('operator_reason_required')
        changed=[]
        from bn_memory.assignment_resources import prepare
        for row in self.rows(sid,run):
            if row['state'] not in {'unknown','blocked','running'}:continue
            body=json.loads(row['body']);receipt=body.get('receipt') or {}
            recorded_failure=receipt.get('terminal_state')=='FAILED' and receipt.get('error_message') in {'bounded_provider_output_required','identity_role_assignment_required'}
            stopped_preflight=row['state']=='running' and not receipt and parent_stopped_attestation is True
            with self.store.db() as db:grant=db.execute('SELECT 1 FROM launch_grants WHERE profile_id=? AND id=?',(self.store.profile,body.get('assignment_id'))).fetchone()
            never_granted=row['state']=='unknown' and body.get('error_class')=='PermissionError' and not body.get('child_sid') and not receipt and grant is None
            if not recorded_failure and not stopped_preflight and not never_granted:raise PermissionError('known_pre_provider_failure_only')
            with self.store.db() as db:
                paid=db.execute("SELECT 1 FROM model_attempts WHERE profile_id=? AND sid=? AND state!='not_dispatched'",(self.store.profile,body['child_sid'])).fetchone()
                evidence=db.execute('SELECT 1 FROM team_evidence WHERE profile_id=? AND assignment=?',(self.store.profile,body['assignment_id'])).fetchone()
            if paid or evidence:raise PermissionError('native_effect_or_provider_outcome_must_be_observed')
            body['previous_products'].append({'input_version':body['input_version'],'receipt':receipt,'product':body['product'],'operator_observation':'no admitted provider or tool effect; prior coordinator stopped','operator_attestation_not_automatic_OS_proof':stopped_preflight,'reason':reason})
            body['input_version']+=1;body['receipt']=None;body['product']=None;body['assignment_id']=None;body['child_sid']=None
            body['resource_basis']=sha(canonical(prepare(self.host,sid,body['role'],'preview',body.get('resources',{}),persist=False)))
            self.save(row,body,'planned');changed.append({'task_id':row['id'],'bead_id':row['bead'],'new_input_version':body['input_version']})
        return {'rearmed':changed,'budget_or_history_reset':False,'new_logical_tasks':0}
