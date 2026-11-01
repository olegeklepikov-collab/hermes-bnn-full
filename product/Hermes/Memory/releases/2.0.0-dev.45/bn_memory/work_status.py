"""Versioned substantive work updates; transport receipt is separate from work state."""
import json,time
from bn_memory.store import canonical,sha,SENSITIVE
class WorkStatus:
    def __init__(self,broker):
        self.broker=broker;self.store=broker.store
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS substantive_status(profile_id TEXT,work_id TEXT,revision INTEGER,body TEXT,PRIMARY KEY(profile_id,work_id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS status_requests(profile_id TEXT,sid TEXT,id TEXT,body_hash TEXT,work_id TEXT,revision INTEGER,PRIMARY KEY(profile_id,sid,id))')
            db.execute('CREATE TABLE IF NOT EXISTS status_publications(profile_id TEXT,work_id TEXT,revision INTEGER,state TEXT,receipt TEXT,PRIMARY KEY(profile_id,work_id,revision))')
    def work(self,sid):
        self.store.writable(sid)
        from bn_memory.working import Working
        try:return Working(self.store).binding(sid)
        except PermissionError:return 'SESSION-'+sha(sid)[:24]
    def current(self,sid):
        work=self.work(sid)
        with self.store.db() as db:r=db.execute('SELECT revision,body FROM substantive_status WHERE profile_id=? AND work_id=? ORDER BY revision DESC LIMIT 1',(self.store.profile,work)).fetchone()
        return (work,r[0],json.loads(r[1])) if r else (work,0,None)
    def advance(self,sid,args):
        work,revision,previous=self.current(sid);fingerprint=sha(canonical(args))
        with self.store.db() as db:known=db.execute('SELECT body_hash,revision FROM status_requests WHERE profile_id=? AND sid=? AND id=?',(self.store.profile,sid,args['request_id'])).fetchone()
        if known:
            if known[0]!=fingerprint:raise ValueError('status_request_conflict')
            return {'work_id':work,'revision':known[1],'duplicate':True}
        if revision!=args['expected_revision']:raise ValueError('status_revision_conflict')
        data={k:args.get(k,[] if k in ['completed','blockers'] else '') for k in ['goal','completed','current','next','blockers']}
        for text in [data['goal'],data['current'],data['next'],*data['completed'],*data['blockers']]:
            if not isinstance(text,str) or not text.strip() or SENSITIVE.search(text):raise ValueError('substantive_status_text_required')
        from bn_memory.artifacts import Artifacts
        guard=Artifacts(self.broker);guard.sensitive(canonical(data).encode(),guard.secrets())
        vague={'подготовка работы','обработка полученного результата','подготовка контекста и инструментов'}
        if data['current'].strip().lower().rstrip('.') in vague:raise ValueError('substantive_step_required')
        if previous and previous['content']==data:
            with self.store.db() as db:db.execute('INSERT INTO status_requests VALUES(?,?,?,?,?,?)',(self.store.profile,sid,args['request_id'],fingerprint,work,revision))
            return {'work_id':work,'revision':revision,'duplicate':True,'reason':'no_substantive_change','new_notification':False}
        state=args['state'];artifact=None
        if state=='finished':
            if not args.get('artifact_id'):raise PermissionError('finished_requires_saved_artifact')
            from bn_memory.artifacts import Artifacts
            artifact=Artifacts(self.broker).status(sid,args['artifact_id'])
            if not artifact['sent']:raise PermissionError('delivery_not_confirmed_work_not_finished')
            from bn_memory.working import Working
            try:card,_=Working(self.store)._card(sid)
            except PermissionError as exc:
                if str(exc)!='working_task_binding_required':raise
            else:
                from bn_memory.working_beads import lookup
                primary=lookup(self.broker.config,json.loads(card['primary_ref'])['id'])
                if primary['status']!='closed':raise PermissionError('primary_work_not_closed')
        body={'claims_status':'parent_report_not_independent_semantic_acceptance','content':data,'state':state,'artifact_id':args.get('artifact_id'),'sent':artifact['sent'] if artifact else False,'owner_received':artifact['received_by_owner'] if artifact else False,'created_at':time.time()}
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');latest=db.execute('SELECT max(revision) FROM substantive_status WHERE profile_id=? AND work_id=?',(self.store.profile,work)).fetchone()[0] or 0
            if latest!=revision:raise ValueError('status_revision_conflict')
            db.execute('INSERT INTO substantive_status VALUES(?,?,?,?)',(self.store.profile,work,revision+1,canonical(body)))
            db.execute('INSERT INTO status_requests VALUES(?,?,?,?,?,?)',(self.store.profile,sid,args['request_id'],fingerprint,work,revision+1))
        return {'work_id':work,'revision':revision+1,'body':body,'message':self.render(body),'notification_sent':False}
    def render(self,body):
        v=body['content'];parts=['Цель: '+v['goal']]
        if v['completed']:parts.append('Сделано: '+'; '.join(v['completed']))
        parts+=['Сейчас: '+v['current'],'Далее: '+v['next']]
        if v['blockers']:parts.append('Ограничения: '+'; '.join(v['blockers']))
        return '\n\n'.join(parts)
    def publish(self,sid,args):
        work,revision,body=self.current(sid)
        if not body or revision!=args['expected_revision']:raise ValueError('current_status_revision_required')
        from bn_memory.telegram_delivery import TelegramDelivery
        from bn_memory.artifacts import Artifacts
        transport=TelegramDelivery(self.broker.config);recipient=transport.recipient();text=self.render(body)
        if len(text.encode('utf-16-le'))//2>4096:raise ValueError('substantive_update_exceeds_message_bound_make_it_concise')
        guard=Artifacts(self.broker);guard.sensitive(text.encode(),guard.secrets());transport.preflight(0)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT state,receipt FROM status_publications WHERE profile_id=? AND work_id=? AND revision=?',(self.store.profile,work,revision)).fetchone()
            if old:
                if old[0]!='sent':raise PermissionError('status_delivery_unknown_do_not_repeat')
                return {'revision':revision,'sent':True,'duplicate':True,'receipt':json.loads(old[1])}
            db.execute('INSERT INTO status_publications VALUES(?,?,?,?,?)',(self.store.profile,work,revision,'sending','{}'))
        try:
            message=transport.call('sendMessage',json={'chat_id':recipient['recipient_user_id'],'text':text})
            if str(message['chat']['id'])!=recipient['recipient_user_id'] or message.get('from',{}).get('id')!=recipient['bot_id']:raise PermissionError('status_recipient_mismatch')
            receipt={'chat_id':str(message['chat']['id']),'message_id':message['message_id'],'text_sha256':sha(text),'sent':True}
            with self.store.db() as db:db.execute("UPDATE status_publications SET state='sent',receipt=? WHERE profile_id=? AND work_id=? AND revision=?",(canonical(receipt),self.store.profile,work,revision))
            return {'revision':revision,'sent':True,'receipt':receipt}
        except Exception:
            with self.store.db() as db:db.execute("UPDATE status_publications SET state='unknown' WHERE profile_id=? AND work_id=? AND revision=?",(self.store.profile,work,revision))
            raise PermissionError('status_delivery_not_confirmed')
    def dispatch(self,sid,args):
        if args['action']=='advance':return self.advance(sid,args)
        if args['action']=='publish':return self.publish(sid,args)
        work,revision,body=self.current(sid)
        return {'work_id':work,'revision':revision,'body':body,'message':self.render(body) if body else None}
