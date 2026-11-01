"""Finite signed Research/Foundation calls inside the existing Hermes; no second model loop."""
import json,sys,time,uuid
from pathlib import Path
from bn_memory.store import canonical,sha
from bn_memory.task_authority import Tasks

class MemoryContext:
    def __init__(self,host,sid):self.host,self.sid=host,sid
    def context(self,request):
        self.host.modules.require(self.sid,'research')
        text=self.host.broker.context(self.sid,request['query'],'research-admission-'+sha(request['query'])[:16])
        return {'status':'assembled','scope':request['scope'],'context':text,'context_hash':sha(text),'adapter':'BNN common scoped memory'}
    def save(self,request):
        self.host.modules.require(self.sid,'research')
        result=self.host.store.record(self.sid,{'content':request['content'],'source_ref':'derived:research-lifecycle','kind':'note','scope':'task','request_id':'research-memory-'+sha(request['content'])[:24],
            'concepts':request.get('concepts',[]),'horizon':'working','memory_type':'episodic','classification_reason':'research import event; scientific claims remain unreviewed'})
        self.host.broker.sync(self.sid,3,[result['id']]);read=self.host.store.read(self.sid,result['id'])
        return {'status':'saved','readback_verified':read['content']==request['content'],'primary_id':result['id'],'revision':result['revision'],'claims_accepted':False}
class GraphContext:
    def __init__(self,host,sid):self.host,self.sid=host,sid
    def search(self,request):
        self.host.modules.require(self.sid,'research')
        binding=self.host.store.binding(self.sid)
        result=self.host.broker.worker('graphiti','search',{'query':request['query'],'scopes':self.host.store.scopes(binding)})
        values=[]
        for row in result['records']:
            primary=self.host.store.read(self.sid,row['id'])
            if primary['revision']==row['revision'] and primary['content_hash']==row['content_hash']:values.append(row)
        return {'status':'queried','project_id':request['project_id'],'results':values,'adapter':'BNN typed provenance graph; not Graphiti inference','claims_accepted':False}
    def put_fact(self,request):
        value=MemoryContext(self.host,self.sid).save({'content':request['text'],'concepts':['research-draft',request['source_ref']]})
        observed=self.host.broker.reconcile(self.sid,value['primary_id'],'graphiti')
        if observed['status']!='reconciled':raise PermissionError('actual_graph_projection_not_confirmed')
        return {'status':'written','readback_verified':True,'primary_id':value['primary_id'],'fact_id':request['fact_id'],'claims_accepted':False}

class Research:
    def __init__(self,host):
        self.host=host;cfg=host.config['modules']['research'];self.root=Path(cfg['state_root'])
        sys.path[:0]=cfg['source_paths']
        from hermes_foundation_bridge.runtime import RuntimeCoordinator
        from hermes_foundation_bridge.dolt_state import DoltStateAdapter
        from hermes_foundation_bridge.artifacts import ArtifactService
        self.runtime=RuntimeCoordinator(self.root);self.state=DoltStateAdapter(self.root,executable=cfg['dolt_executable']);self.artifacts=ArtifactService(self.root)
        self.tasks=Tasks(host,module='research')
        with host.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS research_bindings(profile_id TEXT,id TEXT,sid TEXT,revision INTEGER,state TEXT,body TEXT,PRIMARY KEY(profile_id,id))')
            db.execute('CREATE TABLE IF NOT EXISTS research_binding_history(profile_id TEXT,id TEXT,revision INTEGER,sid TEXT,state TEXT,body TEXT,sha256 TEXT,PRIMARY KEY(profile_id,id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS research_deliveries(profile_id TEXT,id TEXT,sid TEXT,run_id TEXT,context_hash TEXT,state TEXT,PRIMARY KEY(profile_id,id))')
    def load(self,sid,run_id):
        self.host.store.writable(sid)
        with self.host.store.db() as db:row=db.execute('SELECT * FROM research_bindings WHERE profile_id=? AND id=?',(self.host.store.profile,run_id)).fetchone()
        if not row:raise PermissionError('owned_research_run_required')
        body=json.loads(row['body']);current=self.host.store.binding(sid)
        if body['owner']!=self.host.store.namespace['owner_id'] or body['project']!=current['project']:raise PermissionError('research_owner_or_project_mismatch')
        return dict(row),body
    def persist(self,run_id,sid,state,body,expected):
        with self.host.store.db() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT revision FROM research_bindings WHERE profile_id=? AND id=?',(self.host.store.profile,run_id)).fetchone()
            if (row[0] if row else 0)!=expected:raise ValueError('research_binding_revision_conflict')
            raw=canonical(body);db.execute('INSERT INTO research_binding_history VALUES(?,?,?,?,?,?,?)',(self.host.store.profile,run_id,expected+1,sid,state,raw,sha(raw)))
            db.execute('INSERT INTO research_bindings VALUES(?,?,?,?,?,?) ON CONFLICT(profile_id,id) DO UPDATE SET sid=excluded.sid,revision=excluded.revision,state=excluded.state,body=excluded.body',
                (self.host.store.profile,run_id,sid,expected+1,state,canonical(body)))
            db.execute('INSERT INTO module_attempts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(profile_id,id) DO UPDATE SET sid=excluded.sid,state=excluded.state,body=excluded.body',
                (self.host.store.profile,sid,run_id,'research',body['bead'],body['input_hash'],'running' if state=='active' else 'succeeded' if state in {'complete','partial'} else state,canonical({'run_id':run_id,'registry_revision':expected+1})))
    def put(self,project,oid,body,host_run,sid,stopping=False):
        if not stopping:self.host.modules.require(sid,'research')
        elif body.get('contract')!='ResearchWorkContractV1' or body.get('status')!='paused':raise PermissionError('only_owned_stop_contract_write_allowed')
        from hermes_foundation_bridge.canonical import sha256_json
        query={'schema_version':1,'database':'kw_core','project_id':project,'object_id':oid};old=self.state.get(query)
        value=self.state.put({**query,'expected_revision':old['object_ref']['revision'] if old['status']=='found' else 0,'schema_id':body['contract'],'object':body,
            'content_hash':sha256_json(body),'operation_id':oid+'-'+sha256_json(body)[:16],'run_id':host_run})
        if value['status'] not in {'committed','no_op'}:raise RuntimeError('Foundation_canonical_write_not_confirmed')
        return value
    def session(self,sid,body):
        from hermes_foundation_bridge.research_session import ResearchSession
        host=self.host
        class BoundSession(ResearchSession):
            def _work(self):
                host.modules.require(sid,'research')
                return super()._work()
        return BoundSession(self.state,self.runtime,self.tasks,MemoryContext(self.host,sid),GraphContext(self.host,sid),
            project_id=body['project'],profile_id=self.host.store.profile,host_run_id=body['host_run'],work_contract_ref=body['work_ref'],holder_id=body['holder'])
    def start(self,sid,args):
        binding=self.host.store.binding(sid);key=sha(canonical([self.host.store.profile,sid,args['request_id']]))[:24];run='r-'+key
        with self.host.store.db() as db:old=db.execute('SELECT body FROM research_bindings WHERE profile_id=? AND id=?',(self.host.store.profile,run)).fetchone()
        if old:
            row,body=self.load(sid,run)
            if body['input_hash']!=sha(canonical(args)):raise ValueError('research_request_id_conflict')
            return {'run_id':run,'bead_id':body['bead'],'state':row['state'],'duplicate':True,'new_research_started':False}
        with self.host.store.db() as db:
            if db.execute("SELECT 1 FROM research_bindings WHERE profile_id=? AND sid=? AND state='active'",(self.host.store.profile,sid)).fetchone():raise PermissionError('pause_current_research_before_starting_another')
        issue=self.tasks.create(sid,'UDR: '+args['question'][:100],args['question'],'research-root-'+key,args.get('parent_bead'))
        bead=issue['id'];holder='BNN-'+key;self.tasks.claim(sid,bead,holder,'claim-'+key)
        body={'owner':self.host.store.namespace['owner_id'],'project':binding['project'],'input_hash':sha(canonical(args)),'bead':bead,'holder':holder,'question':args['question'],
            'work_ref':'WRK-'+key,'host_run':'HOST-'+key,'lease_revision':None,'binding':None,'context':None,'report':None,'initial_sid':sid,'memory_task':binding['task']}
        self.persist(run,sid,'preparing',body,0)
        self.host.modules.require(sid,'research')
        lease=self.runtime.acquire_lease({'schema_version':1,'work_id':bead,'holder_id':holder,'expected_revision':1,'ttl_seconds':7200})
        if lease['status']!='acquired':raise PermissionError('Foundation_lease_not_acquired')
        body['lease_revision']=lease['current_revision'];self.persist(run,sid,'preparing',body,1)
        if args.get('corpus_id'):
            corpus=self.host.document_store().corpus(sid,args['corpus_id'])
            if not {'plan','collect','analyse','verify','report'}<=set(json.loads(corpus['phases'])):raise ValueError('all_five_UDR_document_phases_required')
            body['corpus_id']=args['corpus_id']
        work=self.work(body,'active');self.put(body['project'],body['work_ref'],work,body['host_run'],sid)
        session=self.session(sid,body);context=session.prepare(args['question']);body['binding']=context['host_context'];body['context']=context
        from hermes_research_report.research_workspace import workspace
        value=workspace({'action':'start','run_id':run,'question':args['question'],'mode':args.get('mode','search'),'host_context':body['binding']})
        self.persist(run,sid,'active',body,2)
        self.host.working.bind(sid,{'beads_id':bead})
        return {'run_id':run,'bead_id':bead,'lease_ref':body['binding']['lease_ref'],'admission':context,'workspace':value,'scientific_acceptance':False}
    def work(self,body,state):
        return {'contract':'ResearchWorkContractV1','status':state,'project_id':body['project'],'profile_id':self.host.store.profile,'host_run_id':body['host_run'],'holder_id':body['holder'],
            'bead_id':body['bead'],'lease_revision':body['lease_revision'],'memory_scope':{'tenant_id':body['owner'],'project_id':body['project'],'profile_id':self.host.store.profile,'work_kind':'research'}}
    def release(self,body):
        # SDK 0.14 has acquire/check but no release API. Exact schema-pinned host adapter.
        with self.runtime._connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT holder_id,revision,status FROM leases WHERE work_id=?',(body['bead'],)).fetchone()
            if not row or row['holder_id']!=body['holder'] or row['revision']!=body['lease_revision']:raise PermissionError('own_lease_revision_required')
            db.execute("UPDATE leases SET status='released' WHERE work_id=? AND holder_id=? AND revision=?",(body['bead'],body['holder'],body['lease_revision']))
        return {'holder':body['holder'],'revision':body['lease_revision'],'state':'released','adapter':'exact signed 0.14 runtime schema; supplier source unchanged'}
    def pause(self,sid,run):
        row,body=self.load(sid,run)
        if row['sid']!=sid:raise PermissionError('research_attached_to_another_session')
        if row['state']=='paused':return {'run_id':run,'state':'paused','duplicate':True}
        if row['state']!='active':raise PermissionError('active_research_required')
        with self.host.store.db() as db:
            if db.execute("SELECT 1 FROM module_attempts WHERE profile_id=? AND sid=? AND module='research' AND id!=? AND state IN ('running','unknown') LIMIT 1",(self.host.store.profile,sid,run)).fetchone():raise PermissionError('research_workers_or_effects_not_settled')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='native_tasks'").fetchone() and db.execute("SELECT 1 FROM native_tasks WHERE profile_id=? AND run_id=? AND state IN ('running','launch_reserved','unknown') LIMIT 1",(self.host.store.profile,run)).fetchone():raise PermissionError('research_workers_not_quiescent')
        release=self.release(body);self.put(body['project'],body['work_ref'],self.work(body,'paused'),body['host_run'],sid,stopping=True);body['last_release']=release
        self.persist(run,sid,'paused',body,row['revision']);return {'run_id':run,'state':'paused','data_retained':True,'lease':release}
    def resume(self,sid,run):
        row,body=self.load(sid,run)
        if row['state']=='active':
            if row['sid']!=sid:raise PermissionError('pause_owned_research_before_reattaching')
            return {'run_id':run,'state':'active','duplicate':True}
        if row['state']!='paused':raise PermissionError('paused_research_required')
        with self.host.store.db() as db:
            unsettled=db.execute("SELECT 1 FROM module_attempts WHERE profile_id=? AND sid=? AND module='research' AND state IN ('running','unknown') LIMIT 1",(self.host.store.profile,row['sid'])).fetchone()
        if unsettled:raise PermissionError('research_previous_attempt_requires_observation')
        try:current=self.host.working.binding(sid)
        except PermissionError:current=None
        if current is not None:
            card,_=self.host.working._card(sid)
            if json.loads(card['primary_ref'])['id']!=body['bead']:raise PermissionError('another_current_task_must_be_preserved')
        with self.host.store.db() as db:db.execute('UPDATE sessions SET task=?,context=NULL,turn=NULL WHERE profile_id=? AND sid=?',(body['memory_task'],self.host.store.profile,sid))
        self.host.working.bind(sid,{'beads_id':body['bead']})
        lease=self.runtime.acquire_lease({'schema_version':1,'work_id':body['bead'],'holder_id':body['holder'],'expected_revision':body['lease_revision'],'ttl_seconds':7200})
        if lease['status']!='acquired':raise PermissionError('research_resume_lease_conflict')
        body['lease_revision']=lease['current_revision'];body['previous_sid']=row['sid'];self.put(body['project'],body['work_ref'],self.work(body,'active'),body['host_run'],sid)
        context=self.session(sid,body).prepare(body['question']);body['binding']=context['host_context'];body['context']=context
        from hermes_research_report.research_workspace import root_for,write_json
        run_data=json.loads((root_for(run)/'run.json').read_text());run_data['host_context']=body['binding'];write_json(root_for(run)/'run.json',run_data)
        self.persist(run,sid,'active',body,row['revision']);return {'run_id':run,'bead_id':body['bead'],'state':'active','previous_sid':row['sid'],'lease_revision':body['lease_revision'],'recollected_sources':0}

    def active(self,sid):
        root=self.host.store.binding(sid)
        while root['parent']:root=self.host.store.binding(root['parent'])
        with self.host.store.db() as db:rows=db.execute("SELECT id FROM research_bindings WHERE profile_id=? AND sid=? AND state='active'",(self.host.store.profile,root['sid'])).fetchall()
        if len(rows)!=1:raise PermissionError('one_active_native_research_binding_required')
        row,body=self.load(root['sid'],rows[0][0]);session=self.session(root['sid'],body);session.restore(body['binding'])
        return row,body
    def refresh(self,sid):
        row,body=self.active(sid)
        if body.get('finalizing_lifecycle_id'):return body['context']
        session=self.session(sid,body);context=session.prepare(body['question'])
        if context['host_context']!=body['binding']:
            body['binding']=context['host_context'];body['context']=context
            from hermes_research_report.research_workspace import root_for,write_json
            value=json.loads((root_for(row['id'])/'run.json').read_text());value['host_context']=body['binding'];write_json(root_for(row['id'])/'run.json',value)
            self.persist(row['id'],sid,'active',body,row['revision'])
        return context
    def context(self,sid,active=None):
        row,body=active or self.active(sid);binding=self.host.store.binding(sid)
        data={'host_context':body['binding'],'run_id':row['id'],'source':'actual Foundation ResearchSession.prepare; claims unreviewed'}
        if not binding['readonly']:data.update(memory=body['context']['memory_context'],graph=body['context']['graph_results'])
        else:data.update(assignment_id=binding['assignment_id'],parent_evidence_not_inherited=True)
        raw=canonical(data);return '<BN_RESEARCH_CONTEXT sha256="'+sha(raw)+'">\n'+raw+'\n</BN_RESEARCH_CONTEXT>'
    def inject(self,sid,request):
        from bn_memory.plugin import strings
        context=self.context(sid)
        if context in '\n'.join(strings(request)):return
        rows=request.get('messages',request.get('input',[]));row=next(r for r in reversed(rows) if r.get('role')=='user')
        if isinstance(row['content'],str):row['content']+='\n'+context
        else:row['content'].append({'type':'input_text' if 'input' in request else 'text','text':context})
    def validate_model(self,sid,request,api_id):
        from bn_memory.plugin import strings
        active=self.active(sid);context=self.context(sid,active)
        if context not in '\n'.join(strings(request)):raise PermissionError('actual_Research_context_not_delivered_intact')
        row,_=active;identifier=api_id+'.'+sha(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}}))
        with self.host.store.db() as db:db.execute('INSERT INTO research_deliveries VALUES(?,?,?,?,?,?)',(self.host.store.profile,identifier,sid,row['id'],sha(context),'scheduled'))
        return identifier
    def confirm(self,identifier,error=False):
        with self.host.store.db() as db:db.execute('UPDATE research_deliveries SET state=? WHERE profile_id=? AND id=?',('failed' if error else 'received',self.host.store.profile,identifier))
    def recover_finish(self,sid,run,args):
        row,body=self.load(sid,run)
        if row['sid']!=sid:raise PermissionError('current_research_binding_required')
        operation='ROP-'+sha(canonical([self.host.store.profile,run,'udr_finish',args['request_id']]))[:24]
        if row['state'] in {'complete','partial'} and body.get('completion'):
            import hashlib
            from hermes_research_report.research_workspace import root_for
            if hashlib.sha256((root_for(run)/'report.md').read_bytes()).hexdigest()!=args['report_sha256']:raise PermissionError('saved_report_hash_mismatch')
            if row['state']=='complete':self.tasks.close_owned(sid,body['bead'],body['holder'],'close-'+run,'Verified saved research report finalized; conclusions remain unreviewed')
            value={'report':body['report'],'Foundation':body['completion'],'state':row['state'],'scientific_acceptance':False,'delivery_authorized':False,'recovered_saved_report':True,'new_research_or_model_calls':0}
            with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='succeeded',body=? WHERE profile_id=? AND id=?",(canonical(value),self.host.store.profile,operation))
            return value
        if row['state']!='active':raise PermissionError('active_or_imported_research_required')
        with self.host.store.db() as db:old=db.execute('SELECT * FROM module_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,operation)).fetchone()
        if not old or old['state'] not in {'running','unknown'}:raise PermissionError('unsettled_finish_operation_required')
        from hermes_research_report.research_workspace import root_for
        root=root_for(run);report=root/'report.md'
        import hashlib
        actual=hashlib.sha256(report.read_bytes()).hexdigest()
        if actual!=args['report_sha256']:raise PermissionError('saved_report_hash_mismatch')
        # SDK finish saved this authoritative receipt before Foundation import failed.
        result=json.loads((root/'result.json').read_text())
        if result['report_sha256']!=actual:raise PermissionError('SDK_report_receipt_mismatch')
        lifecycle=self.state.get({'schema_version':1,'database':'kw_context','project_id':body['project'],'object_id':args['lifecycle_id']})
        if lifecycle.get('status')!='found' or lifecycle['object_ref']['content_hash']!=args['lifecycle_sha256']:raise PermissionError('expected_native_lifecycle_version_required')
        life=lifecycle['object']
        if life['run_id']!=run or life['host_context']['lease_ref']!=body['binding']['lease_ref']:raise PermissionError('lifecycle_belongs_to_other_run_or_lease')
        if hashlib.sha256((Path(life['package_root'])/'report.md').read_bytes()).hexdigest()!=actual:raise PermissionError('frozen_package_report_mismatch')
        with self.host.store.db() as db:history=[json.loads(r[0]) for r in db.execute('SELECT body FROM research_binding_history WHERE profile_id=? AND id=? ORDER BY revision',(self.host.store.profile,run))]
        original=next((h for h in history if h.get('binding')==life['host_context']),None)
        if original is None:raise PermissionError('original_admission_snapshot_missing')
        body.update(binding=original['binding'],context=original['context'],finalizing_lifecycle_id=args['lifecycle_id'])
        self.persist(run,sid,'active',body,row['revision']);row['revision']+=1
        from hermes_research_report.research_workspace import write_json
        saved_run=json.loads((root/'run.json').read_text());saved_run['host_context']=body['binding'];write_json(root/'run.json',saved_run)
        session=self.session(sid,body);session.restore(body['binding']);session.check()
        from hermes_foundation_bridge.research_lifecycle import complete
        receipt=complete(session,self.artifacts,run)
        body['report']=result;body['completion']=receipt;body['last_release']=self.release(body)
        final_state='complete' if result['status']=='complete' else 'partial'
        self.put(body['project'],body['work_ref'],self.work(body,final_state),body['host_run'],sid);self.persist(run,sid,final_state,body,row['revision'])
        if final_state=='complete':self.tasks.close_owned(sid,body['bead'],body['holder'],'close-'+run,'Verified saved report recovered and imported; conclusions unreviewed')
        value={'report':result,'Foundation':receipt,'state':final_state,'scientific_acceptance':False,'delivery_authorized':False,'recovered_saved_report':True,'new_research_or_model_calls':0}
        with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='succeeded',body=? WHERE profile_id=? AND id=?",(canonical(value),self.host.store.profile,operation))
        return value
    def call(self,sid,turn,name,args):
        self.host.modules.require(sid,'research');self.host.store.writable(sid);self.host.admission.ready(sid,turn)
        if name=='udr_workspace' and args['action']=='start':return self.start(sid,args)
        run=args['run_id'];row,body=self.load(sid,run)
        operation=None
        if name in {'udr_source','udr_note','udr_finish'}:
            operation='ROP-'+sha(canonical([self.host.store.profile,run,name,args['request_id']]))[:24];fingerprint=sha(canonical(args))
            with self.host.store.db() as db:previous=db.execute('SELECT * FROM module_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,operation)).fetchone()
            if previous:
                if previous['input_hash']!=fingerprint:raise ValueError('research_operation_id_conflict')
                if previous['state']!='succeeded':raise PermissionError('research_operation_requires_effect_observation')
                return {'duplicate':True,'result':json.loads(previous['body']),'new_effects':0}
        if name=='udr_workspace':
            if args['action']=='revise_report':
                from bn_memory.report_revision import revise
                return revise(self,sid,run,args)
            if args['action']=='status':return {'run_id':run,'bead_id':body['bead'],'state':row['state'],'revision':row['revision'],'lease_revision':body['lease_revision'],'research_lifetime':'durable; independent of execution lease'}
            if args['action']=='pause':return self.pause(sid,run)
            if args['action']=='resume':return self.resume(sid,run)
            if args['action']=='refresh':return self.refresh(sid)
            if args['action']=='recover_finish':return self.recover_finish(sid,run,args)
        if row['sid']!=sid or row['state']!='active':raise PermissionError('current_active_research_required')
        session=self.session(sid,body);session.restore(body['binding']);session.check()
        if operation:
            with self.host.store.db() as db:db.execute('INSERT INTO module_attempts VALUES(?,?,?,?,?,?,?,?)',(self.host.store.profile,sid,operation,'research',body['bead'],fingerprint,'running','{}'))
        if name=='udr_team':
            from bn_memory.teams import Team
            team=Team(self)
            if args['action']=='plan':return team.plan(sid,run,args)
            if args['action']=='run':return team.run(sid,turn,run,args.get('expected_revisions'))
            if args['action']=='status':return team.status(sid,run)
            if args['action']=='continue':return team.continue_task(sid,run,args)
        from hermes_research_report.research_workspace import source,note,finish,workspace
        def recorded(value):
            if operation:
                with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='succeeded',body=? WHERE profile_id=? AND id=?",(canonical(value),self.host.store.profile,operation))
            return value
        if name=='udr_source':return recorded(source(args))
        if name=='udr_note':return recorded(note(args))
        if name=='udr_workspace':return workspace(args)
        if name=='udr_finish':
            if body.get('corpus_id'):
                coverage=self.host.document_store().status(sid,{'corpus_id':body['corpus_id']})
                if not all(coverage['phases'].get(phase,{}).get('complete') for phase in ['plan','collect','analyse','verify','report']):raise PermissionError('mandatory_UDR_document_phase_coverage_incomplete')
            from hermes_foundation_bridge.research_lifecycle import complete
            from hermes_foundation_bridge.canonical import sha256_json
            result=finish(args)
            body['finalizing_lifecycle_id']='RLC-'+sha256_json({'host':body['binding'],'run_id':run})[:24]
            self.persist(run,sid,'active',body,row['revision']);row['revision']+=1
            receipt=complete(session,self.artifacts,run)
            body['report']=result;body['completion']=receipt;body['last_release']=self.release(body)
            final_state='complete' if result['status']=='complete' else 'partial'
            self.put(body['project'],body['work_ref'],self.work(body,final_state),body['host_run'],sid);self.persist(run,sid,final_state,body,row['revision'])
            if final_state=='complete':self.tasks.close_owned(sid,body['bead'],body['holder'],'close-'+run,'Research artifact imported and verified; conclusions unreviewed')
            return recorded({'report':result,'Foundation':receipt,'state':final_state,'scientific_acceptance':False,'delivery_authorized':False})
        raise ValueError('research_operation_not_supported')
