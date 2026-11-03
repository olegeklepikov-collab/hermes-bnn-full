"""One broker for all BN modules; local authority survives derived-service outages."""
import fcntl
import json
import os
import subprocess
import signal
import time
from pathlib import Path
from bn_memory.store import Store,canonical,sha,SENSITIVE
from bn_memory.workers import http

class Broker:
    def __init__(self,config):
        self.config=config;self.store=Store(config['state_root'],config)

    def worker(self,backend,operation,payload=None):
        from bn_memory.backend_policy import BackendPolicy
        BackendPolicy(self.config).require(backend,operation)
        executable=self.config['graph_python'] if backend=='graphiti' else self.config['zvec_python'] if backend=='zvec' else self.config['python']
        if backend=='zvec':
            from bn_memory.embedding_contract import space
            payload=dict(payload or {})
            expected=space(self.config)['space_id']
            if payload.get('space_id',expected)!=expected:raise PermissionError('vector_space_mismatch')
            payload['space_id']=expected
        req={'config':self.config,'backend':backend,'operation':operation,'payload':payload or {}}
        deadline=self.config.get('backend_read_timeout_seconds',120) if backend in {'serena','mirage'} else 12
        import math
        if type(deadline) not in {int,float} or not math.isfinite(deadline) or deadline<=0:raise ValueError('invalid_backend_read_timeout')
        process=subprocess.Popen([executable,str(Path(__file__).with_name('workers.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:stdout,_=process.communicate(canonical(req),timeout=deadline)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate();raise RuntimeError('bounded_backend_timeout')
        finally:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        try:value=json.loads(stdout)
        except ValueError:raise RuntimeError('backend_result_invalid')
        if process.returncode:raise RuntimeError(value.get('code','backend_failed'))
        target=self.config.get('projection_targets',{}).get(backend)
        if target and isinstance(value,dict):value['projection_target']=target
        return value

    def embedding_result(self,texts,input_type):
        from bn_memory.embeddings import Embeddings
        from bn_memory.backend_policy import BackendPolicy
        engine=Embeddings(self.store,self.config,http,authorize=lambda purpose:BackendPolicy(self.config).require('embedding',purpose))
        values=engine.many(texts,input_type)
        return {'vectors':values,'receipt':engine.receipt}

    def reconcile(self,sid,identifier,backend):
        self.store.writable(sid)
        from bn_memory.backend_policy import BackendPolicy
        BackendPolicy(self.config).require(backend,'search')
        with self.store.db() as db:
            row=db.execute('SELECT r.* FROM records r JOIN current c ON c.id=r.id AND c.revision=r.revision WHERE r.id=?',(identifier,)).fetchone()
            if not row or row['scope'] not in self.store.scopes(self.store.binding(sid)):raise PermissionError('projection_outside_scope')
            row=dict(row)
        executable=self.config['graph_python'] if backend=='graphiti' else self.config['zvec_python'] if backend=='zvec' else self.config['python']
        run=subprocess.run([executable,str(Path(__file__).with_name('projection_observe.py'))],input=canonical({'config':self.config,'record':row,'backend':backend}),text=True,capture_output=True,timeout=60)
        if run.returncode:raise RuntimeError('native_projection_observation_failed')
        result=json.loads(run.stdout)
        if not result.get('matched'):return {'status':'unknown','id':identifier,'backend':backend,'observation':result,'replayed':False}
        with self.store.db() as db:
            current=db.execute('SELECT revision FROM current WHERE id=?',(identifier,)).fetchone()
            if not current or current[0]!=row['revision']:raise RuntimeError('primary_changed_during_projection_observation')
            db.execute("UPDATE outbox SET status='indexed',receipt=? WHERE id=? AND revision=? AND backend=?",(canonical(result),identifier,row['revision'],backend))
        return {'status':'reconciled','id':identifier,'backend':backend,'receipt':result,'replayed':False}

    def embedding_many(self,texts,input_type):
        return self.embedding_result(texts,input_type)['vectors']

    def cached_query_embedding(self,text):
        from bn_memory.embeddings import Embeddings
        return Embeddings(self.store,self.config).cached(text,'query')

    def embedding(self,text,input_type):
        return self.embedding_many([text],input_type)[0]

    def sync(self,sid,limit=3,record_ids=None):
        self.store.writable(sid)
        if type(limit) is not int or not 1<=limit<=10:raise ValueError('sync_limit_invalid')
        lock=Path(self.config['state_root'])/'derived.lock';out=[]
        with lock.open('a') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return {'status':'busy','results':[]}
            with self.store.db() as c:
                scopes=self.store.scopes(self.store.binding(sid))
                restriction=' AND r.id IN ('+','.join('?' for _ in record_ids)+')' if record_ids else ''
                rows=c.execute('SELECT r.*,o.backend FROM outbox o JOIN current u ON o.id=u.id AND o.revision=u.revision JOIN records r ON r.id=o.id AND r.revision=o.revision WHERE o.status=\'pending\' AND r.scope IN (?,?,?) AND COALESCE(json_extract(o.receipt,\'$.retry_after\'),0)<=?'+restriction+' ORDER BY COALESCE(json_extract(o.receipt,\'$.last_attempt_at\'),0),r.created,o.backend LIMIT ?',(*scopes,time.time(),*(record_ids or []),limit)).fetchall()
            for entry in rows:
                if getattr(self,'stop_event',None) is not None and self.stop_event.is_set():break
                row=dict(entry)
                if row['scope'] not in self.store.scopes(self.store.binding(sid)):continue
                backend=row['backend']
                with self.store.db() as c:
                    old=c.execute('SELECT receipt FROM outbox WHERE id=? AND backend=? AND receipt IS NOT NULL ORDER BY revision DESC LIMIT 1',(row['id'],backend)).fetchone()
                previous=json.loads(old[0]) if old else {}
                payload={'record':row,'previous':previous}
                # Prepare authorization and embeddings before the effectful worker.
                try:
                    from bn_memory.backend_policy import BackendPolicy
                    BackendPolicy(self.config).require(backend,'sync')
                    if backend=='zvec' and row['status']=='recorded':payload['vector']=self.embedding(row['content'],'document')
                except Exception as exc:
                    result={'status':'unavailable','code':type(exc).__name__,'retry_after':time.time()+60}
                    with self.store.db() as c:c.execute('UPDATE outbox SET receipt=? WHERE id=? AND revision=? AND backend=?',(canonical(result),row['id'],row['revision'],backend))
                    out.append({'id':row['id'],'revision':row['revision'],'backend':backend,**result});continue
                # An acknowledged intent survives process death. Unknown effects are not replayed.
                with self.store.db() as c:
                    claimed=c.execute("UPDATE outbox SET status='in_flight',receipt=? WHERE id=? AND revision=? AND backend=? AND status='pending'",(canonical({'status':'unknown','started_at':time.time()}),row['id'],row['revision'],backend)).rowcount
                if claimed!=1:continue
                try:
                    result=self.worker(backend,'sync',payload);status='indexed'
                    if not isinstance(result,dict) or result.get('status') not in {'indexed','deleted'}:raise RuntimeError('projection_acknowledgement_missing')
                except Exception as exc:
                    attempts=int(previous.get('attempts',0))+1
                    result={**previous,'status':'unknown','code':type(exc).__name__,'attempts':attempts,
                        'last_attempt_at':time.time(),'retry_after':time.time()+min(60*2**min(attempts-1,6),3600)};status='unknown'
                with self.store.db() as c:c.execute('UPDATE outbox SET status=?,receipt=? WHERE id=? AND revision=? AND backend=?',(status,canonical(result),row['id'],row['revision'],backend))
                out.append({'id':row['id'],'revision':row['revision'],'backend':backend,**result})
        with self.store.db() as c:
            unsettled=c.execute("SELECT count(*) FROM outbox o JOIN current u ON u.id=o.id AND u.revision=o.revision JOIN records r ON r.id=u.id AND r.revision=u.revision WHERE r.scope IN (?,?,?) AND o.status IN ('unknown','in_flight')",self.store.scopes(self.store.binding(sid))).fetchone()[0]
        return {'status':'complete' if not unsettled and all(x.get('status') not in {'unavailable','unknown'} for x in out) else 'degraded','results':out,'unsettled_projections':unsettled}

    def sources(self):
        if not self.config.get('source_index_enabled',False):return None
        if not hasattr(self,'_sources'):
            from bn_memory.source_index import SourceIndex
            self._sources=SourceIndex(self)
        return self._sources

    def context(self,sid,query,turn):
        from bn_memory.retrieval import context
        return context(self,sid,query,turn)

    def recall(self,sid,args):
        from bn_memory.retrieval import recall
        return recall(self,sid,args)

    def sync_all(self,limit=10):
        with self.store.db() as db:
            rows=db.execute("SELECT DISTINCT r.scope FROM outbox o JOIN current u ON u.id=o.id AND u.revision=o.revision JOIN records r ON r.id=u.id AND r.revision=u.revision WHERE o.status='pending' AND COALESCE(json_extract(o.receipt,'$.retry_after'),0)<=?",(time.time(),)).fetchall()
            parents=[dict(r) for r in db.execute('SELECT * FROM sessions WHERE readonly=0 AND profile_id=?',(self.store.profile,))]
        out=[]
        for scope, in rows:
            owner=next((r for r in parents if scope in self.store.scopes(r)),None)
            if owner is None:continue
            result=self.sync(owner['sid'],min(10,limit-len(out)));out.extend(result['results'])
            if len(out)>=limit:break
        return {'results':out}

    def files(self,sid,args):
        child=self.store.binding(sid)['readonly'];action=args.get('action','read')
        if child and action=='ls':raise PermissionError('child_directory_listing_not_qualified')
        root,target=self.store.safe_file(sid,args['path'])
        if action=='ls':
            if not target.is_dir():raise ValueError('directory_required')
            entries=[]
            for p in sorted(target.iterdir()):
                try:self.store.safe_file(sid,str(p))
                except PermissionError:continue
                entries.append(p.name)
            return {'entries':entries[:100],'has_more':len(entries)>100,'backend':'scoped_filesystem','source_root':str(root),'source_path':str(target)}
        if not target.is_file() or target.stat().st_size>self.config.get('file_source_bytes',8*1024*1024):raise ValueError('split_file_required')
        from bn_memory.source_visibility import read_file,Visibility
        original,byte_hash=read_file(target,max_bytes=self.config.get('file_source_bytes',8*1024*1024));text=original.decode('utf-8')
        Visibility(self.store).source(sid,byte_hash)
        if SENSITIVE.search(text):raise ValueError('private_file_not_context')
        start=args.get('offset',0);limit=args.get('limit',8192)
        if type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=8192:raise ValueError('page_invalid')
        result=self.worker('mirage','read',{'project_root':str(root),'tool':'read','arguments':{'path':'/project/'+str(target.relative_to(root))}})
        if read_file(target,max_bytes=self.config.get('file_source_bytes',8*1024*1024))[0]!=original:raise RuntimeError('source_changed_during_read')
        Visibility(self.store).source(sid,byte_hash)
        if child:result={'backend':'scoped_filesystem_with_approved_mirage_read'}
        result.update({'path':str(target.relative_to(root)),'source_root':str(root),'source_path':str(target),'source_sha256':sha(text),'text':text[start:start+limit],'offset':start,'next_offset':start+limit if start+limit<len(text) else None,'has_more':start+limit<len(text),'reading_level':'exact_local_text_page'})
        # Backend native return may repeat the whole file; return only the explicit page.
        result.pop('content',None);return result

    def code(self,sid,args):
        child=self.store.binding(sid)['readonly']
        if child and not self.config.get('w3_enabled'):raise PermissionError('child_project_wide_code_query_not_qualified')
        root,target=self.store.safe_file(sid,args['path']);action=args['action']
        if child:
            from bn_memory.assignment_resources import file
            file(self.store,sid,target,'code')
        if action not in {'overview','symbol','references'}:raise ValueError('code_action_invalid')
        if not target.is_file() or target.stat().st_size>1048576:raise ValueError('bounded_code_file_required')
        text=target.read_text()
        if SENSITIVE.search(text):raise ValueError('private_code_not_context')
        relative=str(target.relative_to(root))
        if action=='overview':name='get_symbols_overview';arguments={'relative_path':relative,'depth':1,'max_answer_chars':12000}
        elif action=='symbol':name='find_symbol';arguments={'relative_path':relative,'name_path_pattern':args['symbol'],'include_body':True,'max_answer_chars':12000}
        else:name='find_referencing_symbols';arguments={'relative_path':relative,'name_path':args['symbol'],'max_answer_chars':12000}
        result=self.worker('serena','read',{'project_root':str(root),'tool':name,'arguments':arguments,**({'code_language':'r'} if target.suffix.lower()=='.r' else {})})
        if SENSITIVE.search(canonical(result)):raise ValueError('private_code_result_not_context')
        def paths(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='relative_path' and isinstance(item,str):yield item
                    elif isinstance(key,str) and key.endswith(('.py','.r','.R','.ts','.js','.sh','.md')):yield key
                    yield from paths(item)
            elif isinstance(value,list):
                for item in value:yield from paths(item)
        for content in result.get('content',[]):
            try:value=json.loads(content)
            except ValueError:continue
            for relative_source in paths(value):self.store.safe_file(sid,str(root/relative_source))
        if sha(target.read_text())!=sha(text):raise RuntimeError('code_changed_during_read')
        if len(canonical(result).encode())>16384:raise ValueError('narrow_symbol_query_required')
        return {**result,'source_sha256':sha(text),'path':relative,'source_root':str(root),'source_path':str(target),'reading_level':'native_symbol_lookup'}

    def dispatch(self,sid,name,args):
        if name in {'service_catalog','service_read','service_job','service_write','service_result','service_file'}:
            from bn_memory.service_engine import dispatch
            return dispatch(self,sid,name,args)
        if name in __import__('bn_memory.research_providers',fromlist=['schemas']).schemas():
            from bn_memory.research_providers import dispatch
            return dispatch(self,sid,name,args)
        if name=='crossref_lookup':
            from bn_memory.public_lookup import lookup
            return lookup(self,sid,args)

        if name=='work_status':
            from bn_memory.work_status import WorkStatus
            return WorkStatus(self).dispatch(sid,args)
        if name=='memory_artifact':
            from bn_memory.artifacts import Artifacts
            return Artifacts(self).dispatch(sid,args)

        if name=='memory_data':
            from bn_memory.data_version import read
            return read(self,sid,args)
        if name=='memory_sync' and args.get('target')=='reconcile':return self.reconcile(sid,args['id'],args['backend'])
        if name=='memory_library':
            from bn_memory.library import Library
            return Library(self).dispatch(sid,args)
        runtime=args.pop('_runtime',None)
        if name=='memory_compute':
            from bn_memory.compute import Compute
            return Compute(self).dispatch(sid,args)
        if name=='memory_working':
            from bn_memory.working import Working
            return Working(self.store).dispatch(sid,args)
        if name=='memory_recovery':
            from bn_memory.recovery import Recovery
            return Recovery(self.store).dispatch(sid,args)
        if name.startswith('document_'):
            from bn_memory.documents import Documents
            docs=Documents(self)
            operations={'document_catalogue':docs.catalogue,'document_partition':docs.partition,'document_extract':docs.extract,'document_describe':docs.describe,'document_read':docs.read,'document_status':docs.status}
            return operations[name](sid,args)
        if name.startswith('knowledge_'):
            from bn_memory.knowledge import Knowledge
            knowledge=Knowledge(self)
            if name=='knowledge_ingest':return knowledge.ingest(sid,args,runtime)
            if name=='knowledge_query':return knowledge.query(sid,args,runtime)
            if name=='knowledge_manage':return knowledge.manage(sid,args,runtime)
        if name=='memory_recall':
            basis=self.store.retrieval_basis(sid)
            args.setdefault('mode','hybrid')
            result=self.recall(sid,args)
            if args.get('mode')=='hybrid' and self.config.get('cognee_enabled') and result.get('remote_calls')!=0:
                try:
                    from bn_memory.knowledge import Knowledge
                    effective=result.get('search_contract',{}).get('effective_query',args['query'])
                    result['knowledge_context']=Knowledge(self).query(sid,{'query':effective,'limit':3,'mode':'hybrid'},runtime)
                except Exception as exc:result['knowledge_context']={'status':'unavailable','code':type(exc).__name__}
            from bn_memory.recall_results import retain
            return retain(self,sid,result,basis)
        if name=='memory_record':
            if args.get('source_ref','').startswith('local:'):
                _,original=self.store.safe_file(sid,args['source_ref'][6:])
                from bn_memory.source_visibility import read_file
                raw,source_hash=read_file(original,max_bytes=self.config.get('file_source_bytes',8*1024*1024));raw=raw.decode('utf-8')
                if SENSITIVE.search(raw):raise ValueError('private_source_not_memory')
                if args['kind']=='source' and args['content'] not in raw:raise ValueError('source_quote_not_exact')
                deps=list(args.get('source_dependencies',[]));dep={'kind':'source','sha256':source_hash}
                if dep not in deps:deps.append(dep)
                args={**args,'source_ref':args['source_ref']+'#sha256='+source_hash,'source_dependencies':deps}
            r=self.store.record(sid,args);return {**r,'indexes':self.sync(sid,3,[r['id']])}
        if name=='memory_read':
            if args['id'].startswith('RCL-'):
                from bn_memory.recall_results import read
                return read(self,sid,args)
            if 'offset' in args or 'max_chars' in args:raise ValueError('paging_parameters_require_recall_result_id')
            if args['id'].startswith('SRC-') and self.sources():return self.sources().read(sid,args['id'],args.get('revision'))
            return self.store.read(sid,args['id'],args.get('revision'))
        if name=='memory_retract':
            r=self.store.retract(sid,args['id'],args['expected_revision']);return {**r,'indexes':self.sync(sid,3,[r['id']])}
        if name=='memory_sync' and args.get('target')=='lexical':
            if not self.sources():raise PermissionError('source_index_disabled')
            self.store.writable(sid)
            discovered=self.sources().discover(sid)
            return {'discovered_units':discovered,**self.sources().sync(args.get('limit',3),sid,vector=False)}
        if name=='memory_sync':
            value=self.sync(sid,args.get('limit',3))
            if self.sources():
                self.sources().discover(sid);value['sources']=self.sources().sync(args.get('limit',3),sid)
            return value
        if name=='memory_scope':return self.store.select_project(sid,args['project'])
        if name=='memory_status':
            value=self.store.status(sid)
            if self.sources():
                value['source_index']={'status':'child_aggregate_not_qualified'} if self.store.binding(sid)['readonly'] else self.sources().status(sid)
            return value
        if name=='memory_files':return self.files(sid,args)
        if name=='memory_code':return self.code(sid,args)
        raise ValueError('unknown_memory_tool')
