"""Read-only recovery views. A historical checkpoint never grants current authority."""
import hashlib
import json
from bn_memory.store import canonical

from bn_memory.action_retry import UNKNOWN
UNSETTLED = ('prechecked', *UNKNOWN)


class Recovery:
    def __init__(self,store):
        self.store=store

    def _scope(self,sid):
        binding=self.store.binding(sid)
        if binding['readonly'] and (binding['role']=='unassigned' or not binding['assignment_id']):
            raise PermissionError('recovery_child_assignment_required')
        sql="profile_id=? AND sid=? AND json_extract(payload,'$.session.role')=?"
        args=[self.store.profile,sid,binding['role']]
        if binding['readonly']:
            for key in ['assignment_id','parent','project','task']:
                sql+=" AND json_extract(payload,'$.session."+key+"')=?"
                args.append(binding[key])
            from bn_memory.working import Working
            working_basis=Working(self.store).history_basis(sid)
            if working_basis:
                sql+=" AND json_extract(payload,'$.working_basis')=?"
                args.append(working_basis)
            else:sql+=" AND json_extract(payload,'$.working_basis') IS NULL"
        return sql,args

    @staticmethod
    def _page(args):
        offset=args.get('offset',0);size=args.get('page_size',10)
        if type(offset) is not int or offset<0 or type(size) is not int or not 1<=size<=20:
            raise ValueError('recovery_page_invalid')
        return offset,size

    def checkpoints(self,sid,args):
        sql,params=self._scope(sid);offset,size=self._page(args)
        with self.store.db() as db:
            count=db.execute('SELECT count(*) FROM checkpoints WHERE '+sql,params).fetchone()[0]
            rows=db.execute('SELECT id,sha256,created,json_array_length(payload,\'$.messages\') AS message_count FROM checkpoints WHERE '+sql+' ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',(*params,size,offset)).fetchall()
        return {'checkpoints':[dict(row) for row in rows],'total':count,'offset':offset,
                'next_offset':offset+size if offset+size<count else None,'has_more':offset+size<count,
                'reading_level':'metadata_only','restores_authority':False}

    def pending(self,sid,args):
        self.store.binding(sid);offset,size=self._page(args)
        sql='profile_id=? AND sid=? AND status IN (?,?,?,?,?)';params=(self.store.profile,sid,*UNSETTLED)
        with self.store.db() as db:
            count=db.execute('SELECT count(*) FROM action_attempts WHERE '+sql,params).fetchone()[0]
            rows=db.execute('SELECT nonce,turn_id,call_id,tool_name,effect,input_hash,status,created FROM action_attempts WHERE '+sql+' ORDER BY created,nonce LIMIT ? OFFSET ?',(*params,size,offset)).fetchall()
        return {'actions':[dict(row) for row in rows],'total':count,'offset':offset,
                'has_more':offset+size<count,'next_offset':offset+size if offset+size<count else None,
                'retry_permission':False,'instruction':'Verify actual effects before any retry. An unsettled outcome is not zero effect.'}

    def _verified(self,db,sid,identifier):
        sql,params=self._scope(sid)
        row=db.execute('SELECT rowid,id,sha256 FROM checkpoints WHERE '+sql+' AND id=?',(*params,identifier)).fetchone()
        if row is None:raise PermissionError('checkpoint_not_owned_or_assignment_changed')
        digest=hashlib.sha256()
        with db.blobopen('checkpoints','payload',row['rowid'],readonly=True) as blob:
            while block:=blob.read(1048576):digest.update(block)
        if digest.hexdigest()!=row['sha256']:raise PermissionError('checkpoint_integrity_failed')
        return row

    def load(self,sid,identifier):
        with self.store.db() as db:
            db.execute('BEGIN')
            self._verified(db,sid,identifier)
            return json.loads(db.execute('SELECT payload FROM checkpoints WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()[0])

    def read(self,sid,args):
        identifier=args.get('checkpoint_id');section=args.get('section','messages')
        start=args.get('offset',0);size=args.get('max_chars',8192);index=args.get('message_index',0)
        if not isinstance(identifier,str) or not identifier or section not in {'messages','state'}:
            raise ValueError('checkpoint_reference_and_section_required')
        if type(start) is not int or start<0 or type(size) is not int or not 1<=size<=8192 or type(index) is not int or index<0:
            raise ValueError('checkpoint_fragment_invalid')
        with self.store.db() as db:
            db.execute('BEGIN');row=self._verified(db,sid,identifier)
            if section=='messages':
                count=db.execute("SELECT json_array_length(payload,'$.messages') FROM checkpoints WHERE rowid=?",(row['rowid'],)).fetchone()[0]
                if index>=count:raise ValueError('checkpoint_message_outside_range')
                expression='json_extract(payload,?)';params=[f'$.messages[{index}]']
            else:
                count=None
                expression="json_object('session',json_remove(json_extract(payload,'$.session'),'$.context'),'policy',json_extract(payload,'$.policy'),'working',json_extract(payload,'$.working'),'identity_reference',json_extract(payload,'$.identity_reference'),'basis',json_extract(payload,'$.basis'),'provenance',json_extract(payload,'$.provenance'))"
                params=[]
            length=db.execute('SELECT length('+expression+') FROM checkpoints WHERE rowid=?',(*params,row['rowid'])).fetchone()[0]
            if start>length:raise ValueError('checkpoint_offset_outside_range')
            text=db.execute('SELECT substr('+expression+',?,?) FROM checkpoints WHERE rowid=?',(*params,start+1,size,row['rowid'])).fetchone()[0]
        end=start+len(text)
        return {'checkpoint_id':identifier,'checkpoint_sha256':row['sha256'],'section':section,
                'message_index':index if section=='messages' else None,'message_count':count,
                'offset':start,'characters':len(text),'total_characters':length,'text':text,
                'fragment_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'has_more':end<length,'next_offset':end if end<length else None,
                'reading_level':'exact_saved_json_view_fragment','evidence_status':'historical_unreviewed',
                'restores_authority':False,'visual_content_read':False}

    def status(self,sid):
        binding=self.store.binding(sid)
        checkpoints=self.checkpoints(sid,{'page_size':1});pending=self.pending(sid,{'page_size':1})
        return {'version':'BNRecoveryV1','profile_id':self.store.profile,'session_id':sid,
                'role':binding['role'],'project':binding['project'],'task':binding['task'],
                'checkpoint_count':checkpoints['total'],'latest_checkpoint':next(iter(checkpoints['checkpoints']),None),
                'unsettled_action_count':pending['total'],'historical_authority_restored':False,
                'history_reading':'reference_only; use memory_recovery read_checkpoint for exact content',
                'retry_requires_effect_verification':pending['total']>0}

    def action_status(self,sid,args):
        binding=self.store.binding(sid)
        if binding['readonly']:raise PermissionError('action_review_status_parent_only')
        from bn_memory.action_review import Reviews
        result=Reviews(self.store).inspect(args.get('nonce'))
        attempt=result['attempt']
        with self.store.db() as db:
            project=db.execute('SELECT project FROM sessions WHERE profile_id=? AND sid=?',(self.store.profile,attempt['sid'])).fetchone()[0]
        if project not in self.store.config['projects']:raise PermissionError('registered_action_project_required')
        review=result['review']
        return {'nonce':attempt['nonce'],'tool_name':attempt['tool_name'],'raw_status':attempt['status'],
                'arguments_sha256':result['arguments_sha256'],'native_executor_stopped':result['native_executor_stopped'],
                'review':{**{key:review[key] for key in ['revision','outcome','conclusion_status']},
                          'evidence':{key:review['evidence'][key] for key in ['bytes','sha256']}} if review else None,
                'permission_granted_by_this_read':False,'operator_review_is_not_automatic_proof':True}

    def dispatch(self,sid,args):
        operations={'status':lambda:self.status(sid),'checkpoints':lambda:self.checkpoints(sid,args),
                    'pending_actions':lambda:self.pending(sid,args),'read_checkpoint':lambda:self.read(sid,args),
                    'action_status':lambda:self.action_status(sid,args)}
        operation=operations.get(args.get('action'))
        if operation is None:raise ValueError('recovery_action_invalid')
        return operation()
