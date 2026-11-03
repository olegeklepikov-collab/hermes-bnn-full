"""Shared observation ledger for physical model calls; unknown usage is never zero."""
import json,time
from bn_memory.store import canonical,sha
class Accounting:
    def __init__(self,host):
        self.host=host
        with host.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS model_attempts(profile_id TEXT,id TEXT,root_sid TEXT,sid TEXT,module TEXT,input_hash TEXT,state TEXT,usage_tokens INTEGER,body TEXT,PRIMARY KEY(profile_id,id))')
            db.execute('CREATE TABLE IF NOT EXISTS auxiliary_model_refs(profile_id TEXT,api_id TEXT,retry INTEGER,model_id TEXT,PRIMARY KEY(profile_id,api_id,retry))')
    def reserve(self,sid,request,identity):
        binding=self.host.store.binding(sid);root=binding
        while root['parent']:root=self.host.store.binding(root['parent'])
        module='base'
        if binding['readonly']:
            with self.host.store.db() as db:row=db.execute('SELECT module FROM launch_grants WHERE profile_id=? AND id=?',(self.host.store.profile,binding['assignment_id'])).fetchone()
            module=row[0]
        fingerprint=sha(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}}));identifier=identity['api_request_id']+'.'+str(identity.get('retry_count',0))+'.'+fingerprint
        try:card,_=self.host.working._card(root['sid']);bead=json.loads(card['primary_ref'])['id']
        except PermissionError:bead=None
        body={'provider':identity.get('provider'),'model':request.get('model'),'bead':bead,'effort':(request.get('reasoning') or {}).get('effort'),'at':time.time(),'budget_mode':'observe','limits':None,'usage_unknown_is_zero':False}
        with self.host.store.db() as db:
            if db.execute('SELECT 1 FROM model_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,identifier)).fetchone():raise PermissionError('physical_model_attempt_already_recorded')
            db.execute('INSERT INTO model_attempts VALUES(?,?,?,?,?,?,?,?,?)',(self.host.store.profile,identifier,root['sid'],sid,module,fingerprint,'reserved',None,canonical(body)))
        return identifier
    def finish(self,identifier,response=None,error=False,not_dispatched=False):
        usage=response.get('usage') if isinstance(response,dict) else getattr(response,'usage',None)
        total=usage.get('total_tokens') if isinstance(usage,dict) else getattr(usage,'total_tokens',None)
        if type(total)is not int or total<0:total=None
        with self.host.store.db() as db:
            row=db.execute('SELECT state FROM model_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,identifier)).fetchone()
            if not row:return
            if row[0]!='reserved':return
            state='not_dispatched' if not_dispatched else 'outcome_unknown' if error else 'returned_usage_known' if total is not None else 'returned_usage_unknown'
            db.execute('UPDATE model_attempts SET state=?,usage_tokens=? WHERE profile_id=? AND id=?',(state,0 if not_dispatched else total,self.host.store.profile,identifier))
    def status(self,sid):
        root=self.host.store.binding(sid)
        while root['parent']:root=self.host.store.binding(root['parent'])
        try:card,_=self.host.working._card(root['sid']);bead=json.loads(card['primary_ref'])['id']
        except PermissionError:bead=None
        with self.host.store.db() as db:rows=[dict(r) for r in db.execute("SELECT module,state,count(*) AS physical_attempts,sum(usage_tokens) AS known_tokens FROM model_attempts WHERE profile_id=? AND (root_sid=? OR (? IS NOT NULL AND json_extract(body,'$.bead')=?)) GROUP BY module,state",(self.host.store.profile,root['sid'],bead,bead))]
        return {'root_sid':root['sid'],'primary_bead':bead,'rows':rows,'budget_mode':'observe','unknown_usage_not_zero':True,'same_physical_attempt_not_counted_twice':True}
    def reserve_auxiliary(self,sid,request,identity):
        identifier=self.reserve(sid,request,identity)
        with self.host.store.db() as db:db.execute('INSERT INTO auxiliary_model_refs VALUES(?,?,?,?)',(self.host.store.profile,identity['api_request_id'],identity.get('retry_count',0),identifier))
        return identifier
    def auxiliary_finished(self,api_request_id='',retry_count=0,usage=None,error=None,error_type=None,streaming=False,**kw):
        with self.host.store.db() as db:row=db.execute('SELECT model_id FROM auxiliary_model_refs WHERE profile_id=? AND api_id=? AND retry=?',(self.host.store.profile,api_request_id,retry_count)).fetchone()
        if row:
            if streaming and not error_type and not error:
                with self.host.store.db() as db:db.execute("UPDATE model_attempts SET state='stream_handed_off_usage_unknown' WHERE profile_id=? AND id=? AND state='reserved'",(self.host.store.profile,row[0]))
            else:self.finish(row[0],{'usage':usage},error=bool(error or error_type))
