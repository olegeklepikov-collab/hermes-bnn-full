"""Useful isolated calculations; receipts are host data, stdout is untrusted output."""
import json
from pathlib import Path
import re
import time

from bn_memory.store import canonical,sha,SENSITIVE


def install(db):
    db.execute('''CREATE TABLE compute_jobs(profile_id TEXT NOT NULL,id TEXT NOT NULL,sid TEXT NOT NULL,
        parent_sid TEXT,project TEXT NOT NULL,task TEXT NOT NULL,assignment_id TEXT NOT NULL,role TEXT NOT NULL,
        input_hash TEXT NOT NULL,input_refs TEXT NOT NULL,basis TEXT NOT NULL,state TEXT NOT NULL,
        receipt TEXT,created REAL NOT NULL,PRIMARY KEY(profile_id,id))''')
    db.execute("INSERT INTO meta VALUES('isolated_compute_contract','1')")


class Compute:
    def __init__(self,broker):self.broker=broker;self.store=broker.store;self.config=broker.config

    def refs(self,sid,identifiers):
        if not isinstance(identifiers,list) or len(identifiers)>128 or len(set(identifiers))!=len(identifiers):raise ValueError('compute_record_set_invalid')
        records=[];refs=[]
        for identifier in identifiers:
            if not isinstance(identifier,str) or not re.fullmatch('MEM-[a-f0-9]{24}',identifier):raise ValueError('compute_record_id_invalid')
            row=self.store.read(sid,identifier)
            records.append({key:row[key] for key in ['id','revision','content','content_hash','source','scope']})
            refs.append({key:row[key] for key in ['id','revision','content_hash','scope']})
        return records,refs

    def row(self,sid,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('CMP-[a-f0-9]{32}',identifier):raise ValueError('compute_job_id_invalid')
        b=self.store.binding(sid)
        with self.store.db() as db:r=db.execute('SELECT * FROM compute_jobs WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
        if not r:raise PermissionError('compute_job_not_available')
        r=dict(r)
        if b['readonly']:
            if (r['sid'],r['assignment_id'],r['role'],r['project'],r['task'])!=(sid,b['assignment_id'],b['role'],b['project'],b['task']):raise PermissionError('compute_job_outside_assignment')
        elif r['sid']!=sid and r['parent_sid']!=sid and not (self.config.get('owner_project_reads') and r['project'] in self.config['projects']):
            raise PermissionError('compute_job_outside_owner_scope')
        return r

    def current_inputs(self,sid,refs):
        for ref in refs:
            row=self.store.read(sid,ref['id'])
            if any(row[key]!=ref[key] for key in ['revision','content_hash','scope']):raise PermissionError('compute_input_changed')

    def view(self,sid,args,duplicate=False):
        row=self.row(sid,args['job_id']);refs=json.loads(row['input_refs'])
        try:self.current_inputs(sid,refs);available=True
        except (PermissionError,KeyError):available=False
        base={'job_id':row['id'],'state':row['state'],'duplicate':duplicate,'inputs_current':available,
              'evidence_status':'unreviewed','meaning_accepted':False,'external_effect_performed':False}
        if not available:
            if args.get('action')=='read':raise PermissionError('compute_input_unavailable_or_changed')
            return {**base,'code':'compute_input_unavailable_or_changed'}
        receipt=json.loads(row['receipt'] or '{}');base['receipt']=receipt
        if args.get('action')!='read':return base
        stream=args.get('stream','stdout');offset=args.get('offset',0);limit=args.get('limit',8192)
        if stream not in {'stdout','stderr'} or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16384:raise ValueError('compute_output_page_invalid')
        if row['state'] not in {'completed','failed','cancelled'}:return {**base,'text':None,'code':'compute_result_not_settled'}
        meta=receipt.get(stream)
        if not meta:return {**base,'text':None,'code':'compute_output_not_available'}
        path=Path(self.config['state_root'])/'compute'/row['id']/'control'/stream
        from bn_memory.source_visibility import read_file
        raw,digest=read_file(path,max_bytes=receipt['limits']['output_bytes']+1)
        if digest!=meta['sha256'] or len(raw)!=meta['bytes']:raise RuntimeError('compute_output_integrity_failed')
        text=raw.decode('utf-8')
        if SENSITIVE.search(text):raise PermissionError('sensitive_compute_output_not_model_context')
        fragment=text[offset:offset+limit];end=offset+len(fragment)
        return {**base,'stream':stream,'text':fragment,'offset':offset,'has_more':end<len(text),'next_offset':end if end<len(text) else None,
                'reading_level':'exact_compute_output_page','source_sha256':digest,'total_characters':len(text)}

    def dispatch(self,sid,args):
        action=args.get('action','run')
        if action in {'status','read'}:
            if set(args)-{'action','job_id','stream','offset','limit'}:raise ValueError('compute_read_arguments_invalid')
            return self.view(sid,args)
        if action!='run' or set(args)-{'action','script','data','record_ids','request_id'}:raise ValueError('compute_run_arguments_invalid')
        from bn_memory.backend_policy import BackendPolicy
        BackendPolicy(self.config).require('compute','run')
        script=args.get('script');request=args.get('request_id')
        if not isinstance(script,str) or not 0<len(script.encode())<=65536 or SENSITIVE.search(script):raise ValueError('compute_script_invalid')
        if not isinstance(request,str) or not 0<len(request)<=128:raise ValueError('compute_request_id_required')
        records,refs=self.refs(sid,args.get('record_ids',[]));payload={'data':args.get('data'),'records':records}
        raw=canonical(payload)
        if len(raw.encode())>2*1024*1024 or SENSITIVE.search(raw):raise ValueError('split_or_remove_sensitive_compute_input')
        binding=self.store.binding(sid);basis=self.store.retrieval_basis(sid)
        input_hash=sha(canonical({'script':script,'payload':payload}));identifier='CMP-'+sha(canonical([self.store.profile,sid,binding['assignment_id'],request]))[:32]
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM compute_jobs WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
            if old and old['input_hash']!=input_hash:raise ValueError('compute_idempotency_conflict')
            if not old:db.execute('INSERT INTO compute_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.store.profile,identifier,sid,binding['parent'],binding['project'],binding['task'],binding['assignment_id'],binding['role'],input_hash,canonical(refs),basis,'prepared',None,time.time()))
        if old:return self.view(sid,{'action':'status','job_id':identifier},duplicate=True)
        root=Path(self.config['state_root'])/'compute';root.mkdir(exist_ok=True,mode=0o700)
        job=root/identifier
        try:
            job.mkdir(mode=0o700);control=job/'control';control.mkdir(mode=0o700)
            source=job/'script.py';inputs=job/'inputs.json';source.write_text(script);inputs.write_text(raw);source.chmod(0o400);inputs.chmod(0o400)
            def before_script():
                if self.store.retrieval_basis(sid)!=basis:raise PermissionError('compute_authority_or_input_changed_before_script')
                self.current_inputs(sid,refs)
                BackendPolicy(self.config).require('compute','run')
            def started(value):
                with (control/'executions.jsonl').open('a') as log:
                    log.write(canonical({**value,'at':time.time()})+'\n');log.flush();__import__('os').fsync(log.fileno())
                with self.store.db() as db:db.execute("UPDATE compute_jobs SET state='running',receipt=? WHERE profile_id=? AND id=?",(canonical({'execution':value}),self.store.profile,identifier))
            from bn_memory.isolated_runtime import run
            result=run(self.config,job,source,inputs,before_script=before_script,started=started)
            receipt={key:value for key,value in result.items() if key not in {'stdout','stderr'}}
            for stream in ['stdout','stderr']:
                data=result[stream];path=control/stream;path.write_bytes(data);path.chmod(0o400)
                receipt[stream]={'sha256':__import__('hashlib').sha256(data).hexdigest(),'bytes':len(data)}
            receipt.update(script_sha256=sha(script),input_sha256=sha(raw),input_refs=refs,input_hash=input_hash)
            state='cancelled' if result['reason']=='compute_cancelled' else 'completed' if result['exit_code']==0 and not result['reason'] else 'failed'
        except Exception as exc:
            receipt={'code':type(exc).__name__+':'+str(exc),'script_not_inferred_success':True}
            state='cancelled' if 'cancelled' in str(exc) else 'failed'
        with self.store.db() as db:db.execute('UPDATE compute_jobs SET state=?,receipt=? WHERE profile_id=? AND id=?',(state,canonical(receipt),self.store.profile,identifier))
        response=self.view(sid,{'action':'status','job_id':identifier})
        if state=='completed':
            response['output']=self.view(sid,{'action':'read','job_id':identifier})
            response['output'].pop('receipt',None)
        return response
