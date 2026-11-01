from bn_memory import COGNEE_VERSION
"""Primary source ledger + a recoverable, scope-bound Cognee derivative."""
import hashlib
import fcntl
import json
import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path
from bn_memory.store import canonical,sha,SENSITIVE

class Knowledge:
    def __init__(self,broker):
        self.broker=broker;self.store=broker.store;self.config=broker.config
        self.root=Path(self.config['cognee_root']);self.artifacts=self.root/'state/originals';self.artifacts.mkdir(exist_ok=True)
        with self.store.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS knowledge_docs(id TEXT PRIMARY KEY,scope TEXT NOT NULL,locator TEXT NOT NULL,source_hash TEXT NOT NULL,text_hash TEXT NOT NULL,text_path TEXT NOT NULL,record_id TEXT,record_revision INTEGER,status TEXT NOT NULL,dataset TEXT NOT NULL,metadata TEXT NOT NULL,receipt TEXT,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge_runs(id TEXT PRIMARY KEY,sid_hash TEXT NOT NULL,scope TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,result TEXT,created REAL NOT NULL);
            ''')
        self.instance=json.loads((self.root/'state/instance.json').read_text())['instance_id']
    def dataset(self,scope):return self.instance+'-'+sha(scope)[:24]
    def docs(self,sid):
        if self.store.binding(sid)['readonly']:raise PermissionError('child_graph_dependency_filter_not_qualified')
        scopes=self.store.scopes(self.store.binding(sid))
        with self.store.db() as c:return [dict(r) for r in c.execute('SELECT * FROM knowledge_docs WHERE scope IN (?,?,?) ORDER BY created',scopes)]
    def _doc(self,sid,docid):
        matches=[r for r in self.docs(sid) if r['id']==docid]
        if not matches:raise PermissionError('knowledge_source_unavailable_in_scope')
        return matches[0]
    def worker(self,operation,payload,runtime=None):
        if not self.config.get('cognee_enabled'):raise RuntimeError('cognee_optional_backend_disabled')
        request={'config':self.config,'operation':operation,'payload':payload,'runtime':runtime}
        env=dict(os.environ)
        for key in list(env):
            if any(word in key for word in ['API_KEY','AUTH_TOKEN','ACCESS_TOKEN','SECRET_KEY','PASSWORD']):env.pop(key)
        lock=(self.root/'state/engine.lock').open('a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:lock.close();raise RuntimeError('cognee_engine_busy')
        process=subprocess.Popen([str(self.root/'software/venv/bin/python'),str(Path(__file__).with_name('cognee_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(self.root/'state'),env=env,start_new_session=True)
        try:stdout,stderr=process.communicate(canonical(request),timeout=(3600 if operation in {'ingest','enrich','lesson'} or operation=='query' and payload.get('mode')=='temporal' else 120) if self.broker.config.get('budget_mode')=='observe' else (330 if operation in {'ingest','enrich','lesson'} or operation=='query' and payload.get('mode')=='temporal' else 40))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate();raise TimeoutError('cognee_finite_operation_timeout')
        finally:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            lock.close()
        value=None
        for line in reversed(stdout.splitlines()):
            try:value=json.loads(line);break
            except ValueError:continue
        if value is None:raise RuntimeError('cognee_worker_invalid_result')
        if process.returncode:raise RuntimeError(value.get('code','cognee_worker_failed'))
        return value
    def _valid(self,row):
        metadata=json.loads(row['metadata'])
        if row.get('record_id'):
            with self.store.db() as c:
                current=c.execute('SELECT r.* FROM records r JOIN current u ON u.id=r.id AND u.revision=r.revision WHERE r.id=?',(row['record_id'],)).fetchone()
            if not current or current['status']!='recorded' or current['revision']!=row['record_revision']:return False
        text=Path(row['text_path']);original=self.artifacts/row['source_hash']
        from bn_memory.documents import filehash
        return text.is_file() and sha(text.read_text())==row['text_hash'] and original.is_file() and filehash(original)==row['source_hash']
    def current_projection(self,row):
        return json.loads(row.get('receipt') or '{}').get('projection_revision')=='dataset-isolation-v2'
    def _guard(self,sid,dataset):
        docs=[r for r in self.docs(sid) if r['dataset']==dataset and r['status'] not in {'forgotten','superseded'}]
        if any(not self._valid(r) or r['status']!='indexed' for r in docs):raise RuntimeError('knowledge_dataset_requires_reconciliation')
        if any(not self.current_projection(r) for r in docs):raise RuntimeError('knowledge_projection_requires_explicit_reindex')
        return docs
    def prepare(self,sid,args):
        self.store.writable(sid);scope=self.store.scope(sid,args.get('scope','project'))
        if bool(args.get('path'))==bool(args.get('record_id')):raise ValueError('one_source_path_or_record_required')
        rid=None;revision=None;locator=None;source_hash=None;unit_metadata={};original=None
        if args.get('record_id'):
            record=self.store.read(sid,args['record_id'],args.get('revision'));rid=record['id'];revision=record['revision'];text=record['content'];original=text.encode();locator='memory:'+rid+':'+str(revision)
        else:
            _,path=self.store.safe_file(sid,args['path'])
            locator='local:'+args['path']
            if self.config.get('mandatory_common_intake'):
                from bn_memory.intake import addressed_unit
                result=addressed_unit(self.broker,sid,str(path),'knowledge-'+args.get('request_id',sha(str(path))),args.get('scope','project'),args.get('unit',0))
                if result['status']!='unit_extracted':return result,False
                text=result['text'];source_hash=result['original_sha256'];original_target=Path(result['original_path'])
                unit_metadata={key:result[key] for key in ['unit','units_total','locator','doc_id','corpus_id','unit_text_sha256','visual_required']}
            else:
                if path.suffix.lower() not in {'.txt','.md','.json','.csv','.tsv','.xml','.html','.py','.r','.sql'}:raise PermissionError('common_document_intake_required')
                if not path.is_file() or path.stat().st_size>8*1024*1024:raise ValueError('bounded_existing_source_required')
                original=path.read_bytes();text=original.decode('utf-8')
        if SENSITIVE.search(text):raise ValueError('private_source_not_admitted')
        offset=args.get('offset',0);length=args.get('length',20000)
        if type(offset) is not int or offset<0 or type(length) is not int or not 1<=length<=20000:raise ValueError('explicit_source_range_required')
        chosen=text[offset:offset+length]
        if not chosen.strip():raise ValueError('source_range_empty')
        source_hash=source_hash or hashlib.sha256(original).hexdigest();oid=self.artifacts/source_hash
        if not oid.exists():
            import shutil
            with oid.open('xb') as target:
                if original is not None:target.write(original)
                else:
                    with original_target.open('rb') as source:shutil.copyfileobj(source,target,1024*1024)
                target.flush();os.fsync(target.fileno())
            oid.chmod(0o600)
        from bn_memory.documents import filehash
        if filehash(oid)!=source_hash:raise RuntimeError('original_integrity_failed')
        docid='KDOC-'+sha(scope+'|'+locator+'|'+source_hash+'|'+str(offset)+'|'+str(length)+('|unit='+str(unit_metadata['unit']) if unit_metadata else ''))[:24];tp=self.artifacts/(docid+'.txt')
        if not tp.exists():tp.write_text(chosen);tp.chmod(0o600)
        from bn_memory.source_visibility import dependencies
        inherited=[{'kind':'record','id':record['id'],'revision':record['revision'],'content_hash':record['content_hash']}] if rid else [{'kind':'source','sha256':source_hash}]
        metadata={'source_dependencies':dependencies(inherited),'bn_doc_id':docid,'source_sha256':source_hash,'text_sha256':sha(chosen),'source_ref':locator,'source_url':args.get('source_url'),'extent':'extracted_text' if args.get('path','').endswith('.pdf') else 'text','offset':offset,'length':len(chosen),'total_chars':len(text),'full_source_processed':offset==0 and len(chosen)==len(text),'claims_accepted':False,'content_type':args.get('content_type','text'),'filename':Path(args.get('path') or 'record.txt').name}
        dataset=self.dataset(scope)
        if unit_metadata:metadata.update(unit_metadata,full_source_processed=unit_metadata['units_total']==1 and offset==0 and len(chosen)==len(text) and not unit_metadata['visual_required'],decoder='common_isolated_parser',visual_verified=False)
        with self.store.db() as c:
            previous=c.execute('SELECT * FROM knowledge_docs WHERE id=?',(docid,)).fetchone()
            if previous and previous['status']=='indexed':
                if not self.current_projection(dict(previous)):raise RuntimeError('knowledge_projection_requires_explicit_reindex')
                return dict(previous),True
            c.execute('INSERT INTO knowledge_docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=\'pending\'',(docid,scope,locator,source_hash,sha(chosen),str(tp),rid,revision,'pending',dataset,canonical(metadata),None,time.time()))
        return self._doc(sid,docid),False
    def ingest(self,sid,args,runtime):
        if not runtime:raise PermissionError('native_executor_required_before_ingestion')
        if not self.config.get('cognee_enabled'):raise PermissionError('cognee_disabled_before_ingestion')
        row,duplicate=self.prepare(sid,args)
        if row.get('status')=='document_intake_pending':return row
        if duplicate:
            result=json.loads(row['receipt'])
            if result.get('primary_fragment_ids'):return {'doc_id':row['id'],'status':'indexed','duplicate':True,'metadata':json.loads(row['metadata']),'primary_fragment_ids':result['primary_fragment_ids']}
        else:
          try:result=self.worker('ingest',{'doc_id':row['id'],'text':Path(row['text_path']).read_text(),'dataset':row['dataset'],'metadata':json.loads(row['metadata'])},runtime)
          except Exception as exc:
            with self.store.db() as c:c.execute('UPDATE knowledge_docs SET status=\'partial\',receipt=? WHERE id=?',(canonical({'failure':type(exc).__name__}),row['id']))
            raise
        result['projection_revision']='dataset-isolation-v2'
        status='indexed' if result.get('result',{}).get('status')=='completed' else 'partial'
        with self.store.db() as c:c.execute('UPDATE knowledge_docs SET status=?,receipt=? WHERE id=?',(status,canonical(result),row['id']))
        if status!='indexed':raise RuntimeError('cognee_ingestion_not_completed')
        # Exact primary fragments enter the existing automatic BN context. They are
        # source text, not machine graph claims; no extra model or index loop here.
        source=Path(row['text_path']).read_text();records=[]
        for index,offset in enumerate(range(0,len(source),2000)):
            part=source[offset:offset+2000]
            records.append(self.store.record(sid,{'content':part,'source_ref':'knowledge:'+row['id']+'#sha256='+row['source_hash']+';chars='+str(offset)+'-'+str(offset+len(part)),'kind':'source','request_id':row['id']+'-part-'+str(index),'scope':args.get('scope','project'),'source_dependencies':json.loads(row['metadata']).get('source_dependencies',[{'kind':'source','sha256':row['source_hash']}])}))
        result['primary_fragment_ids']=[r['id'] for r in records]
        with self.store.db() as c:c.execute('UPDATE knowledge_docs SET receipt=? WHERE id=?',(canonical(result),row['id']))
        return {'status':status,'doc_id':row['id'],'metadata':json.loads(row['metadata']),'primary_fragments':records,'cognee':result,'scientific_acceptance':False}
    def query(self,sid,args,runtime):
        if SENSITIVE.search(args['query']) or len(args['query'])>1024:raise ValueError('bounded_public_query_required')
        rows=[r for r in self.docs(sid) if r['status']=='indexed'];datasets=list(dict.fromkeys(r['dataset'] for r in rows))
        if not datasets:return {'status':'empty','contexts':[],'sources':[],'index_built':False}
        for dataset in datasets:self._guard(sid,dataset)
        result=self.worker('query',{'query':args['query'],'datasets':datasets,'mode':args.get('mode','hybrid'),'limit':args.get('limit',5)},runtime)
        quotes=[];by_id={r['id']:r for r in rows}
        for passage in result.get('passages',[]):
            text=passage.get('text','')
            matches=list(re.finditer(r'bn_doc_id: (KDOC-[0-9a-f]{24})\nsource_sha256: ([0-9a-f]{64})\nsource_ref: ([^\n]+)\nextent: [^\n]+\n',text))
            for i,match in enumerate(matches):
                row=by_id.get(match[1])
                if not row or row['source_hash']!=match[2]:raise RuntimeError('cognee_source_attribution_mismatch')
                stop=matches[i+1].start() if i+1<len(matches) else text.find('\n\n## Relevant entities',match.end())
                if stop<0:stop=text.rfind('`')
                fragment=text[match.end():stop].strip()
                if fragment.endswith('\n---'):fragment=fragment[:-4].rstrip()
                original=Path(row['text_path']).read_text()
                at=original.find(fragment)
                if not fragment or at<0:raise RuntimeError('cognee_passage_not_in_primary_source')
                quotes.append({'doc_id':row['id'],'exact_fragment':fragment,'char_start':at,'char_end':at+len(fragment),'source_sha256':row['source_hash'],'text_sha256':row['text_hash'],'source_ref':row['locator'],'verified_against_primary':True})
        contexts=[]
        for item in result['results']:
            text=item.get('text','');marker='Context:\n`'
            if marker in text:text=text.split(marker,1)[1].rsplit('`',1)[0]
            contexts.append({'kind':item.get('kind'),'search_type':item.get('search_type'),'data':text,'derivation':'model_graph_unreviewed'})
        output={'status':'queried','contexts':contexts,'source_quotes':quotes,'source_attribution':'exact_passages_verified; graph statements require subject review','evidence_status':'unreviewed','only_context':True}
        size=len(canonical(output).encode())
        if size>30000:
            ref='KCTX-'+sha(canonical(output))[:24];target=self.root/'state/contexts';target.mkdir(exist_ok=True);(target/(ref+'.json')).write_text(canonical({'scope':self.store.scopes(self.store.binding(sid)),'payload':output}));output={'status':'context_requires_addressed_read','context_ref':ref,'bytes':size,'not_truncated':True}
        return output
    def manage(self,sid,args,runtime):
        if self.store.binding(sid)['readonly']:raise PermissionError('child_graph_dependency_filter_not_qualified')
        action=args['action']
        if action=='status':return {'version':COGNEE_VERSION,'sources':[{k:r[k] for k in ['id','scope','locator','source_hash','status']} for r in self.docs(sid)],'stores':'isolated sqlite/lancedb/ladybug','claims_accepted':False}
        if action=='read_source':
            row=self._doc(sid,args['doc_id']);text=Path(row['text_path']).read_text()
            if sha(text)!=row['text_hash']:raise RuntimeError('knowledge_source_hash_mismatch')
            offset=args.get('offset',0);page=text[offset:offset+8192]
            return {'doc_id':row['id'],'text':page,'text_sha256':row['text_hash'],'metadata':json.loads(row['metadata']),'has_more':offset+8192<len(text),'next_offset':offset+8192 if offset+8192<len(text) else None,'reading_level':'exact_preserved_text_page'}
        if action=='read_context':
            ref=args['context_ref']
            if not re.fullmatch(r'KCTX-[0-9a-f]{24}',ref):raise ValueError('context_reference_invalid')
            value=json.loads((self.root/'state/contexts'/(ref+'.json')).read_text())
            if value['scope']!=self.store.scopes(self.store.binding(sid)):raise PermissionError('context_outside_scope')
            text=canonical(value['payload']);offset=args.get('offset',0)
            return {'context_ref':ref,'text':text[offset:offset+8192],'has_more':offset+8192<len(text),'next_offset':offset+8192 if offset+8192<len(text) else None,'not_truncated':True}
        self.store.writable(sid)
        if action=='lesson' and not self.config.get('cognee_lesson_enabled',False):raise PermissionError('cognee_lesson_pipeline_not_accepted')
        if not runtime:raise PermissionError('native_executor_required_before_mutation')
        if action=='reindex':
            row=self._doc(sid,args['doc_id'])
            if row['status']=='forgotten' or not self._valid(row):raise PermissionError('valid_nonrevoked_primary_required')
            if not args.get('request_id'):raise ValueError('stable_reindex_request_id_required')
            key='KRUN-'+sha(row['scope']+':reindex:'+row['id']+':'+row['source_hash']+':dataset-isolation-v2:'+args['request_id'])[:24]
            with self.store.db() as c:old=c.execute('SELECT status,result FROM knowledge_runs WHERE id=?',(key,)).fetchone()
            if old:
                if old['status']=='returned' and self.current_projection(row):return {'run_id':key,'result':json.loads(old['result']),'duplicate':True,'scientific_acceptance':False}
                raise RuntimeError('reindex_attempt_requires_operator_reconciliation')
            previous=json.loads(row.get('receipt') or '{}')
            with self.store.db() as c:
                c.execute('INSERT INTO knowledge_runs VALUES(?,?,?,?,?,?,?)',(key,self.store.session_hash(sid),row['scope'],'reindex','pending',canonical({'previous_receipt':previous,'source_hash':row['source_hash']}),time.time()))
                c.execute("UPDATE knowledge_docs SET status='migration_pending' WHERE id=?",(row['id'],))
            try:
                result=self.worker('ingest',{'doc_id':row['id'],'text':Path(row['text_path']).read_text(),'dataset':row['dataset'],'metadata':json.loads(row['metadata'])},runtime)
                if result.get('result',{}).get('status')!='completed':raise RuntimeError('cognee_reindex_not_completed')
            except Exception:
                with self.store.db() as c:c.execute("UPDATE knowledge_docs SET status='migration_partial' WHERE id=?",(row['id'],))
                raise
            result.update(projection_revision='dataset-isolation-v2',primary_fragment_ids=previous.get('primary_fragment_ids',[]),source_hash=row['source_hash'],previous_projection_receipt=previous)
            with self.store.db() as c:
                c.execute("UPDATE knowledge_docs SET status='indexed',receipt=? WHERE id=?",(canonical(result),row['id']))
                c.execute("UPDATE knowledge_runs SET status='returned',result=? WHERE id=?",(canonical(result),key))
            return {'run_id':key,'doc_id':row['id'],'status':'reindexed','result':result,'primary_original_unchanged':True,'legacy_projection_preserved':True,'scientific_acceptance':False}
        scope=self.store.scope(sid,args.get('scope','project'));dataset=self.dataset(scope)
        if action=='forget':
            row=self._doc(sid,args['doc_id']);receipt=json.loads(row['receipt'] or '{}')
            # remember.items covers the WHOLE dataset, not the requested source.
            # Resolve ownership from the exact external source ID before deletion.
            data_ids=self.worker('resolve_ids',{'dataset':row['dataset'],'doc_id':row['id']},runtime)['data_ids']
            if not data_ids and row['status']=='indexed':raise RuntimeError('exact_cognee_data_id_required')
            result=[self.worker('forget',{'dataset':row['dataset'],'data_id':x},runtime) for x in data_ids]
            for rid in receipt.get('primary_fragment_ids',[]):
                try:primary=self.store.read(sid,rid)
                except PermissionError as exc:
                    if str(exc)!='record_retracted':raise
                else:self.store.retract(sid,rid,primary['revision'])
            with self.store.db() as c:c.execute('UPDATE knowledge_docs SET status=\'forgotten\' WHERE id=?',(row['id'],))
            return {'status':'forgotten','doc_id':row['id'],'original_preserved':True,'results':result}
        self._guard(sid,dataset)
        if action=='enrich':result=self.worker('enrich',{'dataset':dataset},runtime)
        elif action=='lesson':
            record=self.store.read(sid,args['record_id'])
            key='KRUN-'+sha(scope+':lesson:'+args['request_id'])[:24]
            with self.store.db() as c:old=c.execute('SELECT result FROM knowledge_runs WHERE id=?',(key,)).fetchone()
            if old:
                cached=json.loads(old[0]);source=cached.get('primary_input',{})
                if any(source.get(k)!=record[k] for k in ['id','revision','content_hash']):raise ValueError('lesson_request_input_conflict')
                return {'run_id':key,'result':cached,'duplicate':True,'scientific_acceptance':False,'evidence_status':'unreviewed'}
            fingerprint=sha(record['id']+':'+str(record['revision'])+':'+record['content_hash'])[:24]
            result=self.worker('lesson',{'engine_scope':scope,'dataset':dataset+'-lesson-'+fingerprint,'session_id':'BNLESSON-'+sha(scope+':'+args['request_id'])[:24],'text':record['content'],'source':{k:record[k] for k in ['id','revision','content_hash','source']}},runtime)
        else:raise ValueError('knowledge_action_not_admitted')
        if action!='lesson':key='KRUN-'+uuid.uuid4().hex[:24]
        if action=='lesson':
            result['primary_input']={k:record[k] for k in ['id','revision','content_hash','source']}
            result['candidate_record_ids']=[]
            for index,text in enumerate(result.get('result',{}).get('documents',[])):
                candidate=self.store.record(sid,{'content':text,'source_ref':'derived:cognee:'+key+';input='+record['id']+':'+str(record['revision'])+';sha256='+record['content_hash'],'kind':'candidate','request_id':key+'-'+str(index),'scope':args.get('scope','project')})
                result['candidate_record_ids'].append(candidate['id'])
        with self.store.db() as c:c.execute('INSERT INTO knowledge_runs VALUES(?,?,?,?,?,?,?)',(key,self.store.session_hash(sid),scope,action,'returned',canonical(result),time.time()))
        return {'run_id':key,'result':result,'scientific_acceptance':False,'evidence_status':'unreviewed'}
