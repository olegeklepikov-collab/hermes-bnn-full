"""Versioned working data beside the single Beads graph, never action authority."""
import hashlib
import json
import time
from bn_memory.store import canonical,sha,SENSITIVE
from bn_memory.record_metadata import attributes,ROLES

KINDS={'goal','constraint','decision','obligation','unknown'}


def install(db):
    schema='''
    CREATE TABLE working_cards(profile_id TEXT NOT NULL,work_id TEXT NOT NULL,project TEXT NOT NULL,primary_ref TEXT NOT NULL,PRIMARY KEY(profile_id,work_id));
    CREATE TABLE working_revisions(profile_id TEXT NOT NULL,work_id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(profile_id,work_id,revision));
    CREATE TABLE working_bindings(profile_id TEXT NOT NULL,sid TEXT NOT NULL,work_id TEXT NOT NULL,PRIMARY KEY(profile_id,sid),FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid));
    CREATE TABLE working_sources(profile_id TEXT NOT NULL,id TEXT NOT NULL,sid TEXT NOT NULL,turn_id TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL,project TEXT NOT NULL,PRIMARY KEY(profile_id,id));
    CREATE TABLE working_actions(profile_id TEXT NOT NULL,nonce TEXT NOT NULL,work_id TEXT NOT NULL,sid TEXT NOT NULL,PRIMARY KEY(profile_id,nonce),FOREIGN KEY(profile_id,nonce) REFERENCES action_attempts(profile_id,nonce));
    '''
    for statement in schema.split(';'):
        if statement.strip():db.execute(statement)
    db.execute("INSERT INTO meta VALUES('working_contract','1')")


def inherit(db,profile,parent,child):
    row=db.execute('SELECT work_id FROM working_bindings WHERE profile_id=? AND sid=?',(profile,parent)).fetchone()
    db.execute('DELETE FROM working_bindings WHERE profile_id=? AND sid=?',(profile,child))
    if row:db.execute('INSERT INTO working_bindings VALUES(?,?,?)',(profile,child,row[0]))


def link_action(db,profile,sid,nonce):
    row=db.execute('SELECT work_id FROM working_bindings WHERE profile_id=? AND sid=?',(profile,sid)).fetchone()
    if row:db.execute('INSERT INTO working_actions VALUES(?,?,?,?)',(profile,nonce,row[0],sid))


class Working:
    def __init__(self,store):self.store=store;self.profile=store.profile

    def capture(self,sid,turn,content):
        if not self.store.config.get('working_beads') or self.store.binding(sid)['readonly']:return
        text=content if isinstance(content,str) else canonical(content)
        if SENSITIVE.search(text):return
        identifier='INPUT-'+sha(canonical([self.store.namespace,sid,turn,text]))[:24]
        with self.store.db() as db:
            db.execute('INSERT OR IGNORE INTO working_sources VALUES(?,?,?,?,?,?,?)',
                       (self.profile,identifier,sid,turn,text,sha(text),self.store.binding(sid)['project']))

    def binding(self,sid):
        self.store.binding(sid)
        with self.store.db() as db:
            row=db.execute('SELECT * FROM working_bindings WHERE profile_id=? AND sid=?',(self.profile,sid)).fetchone()
        if row is None:raise PermissionError('working_task_binding_required')
        return row['work_id']

    def bind(self,sid,args):
        binding=self.store.writable(sid)
        from bn_memory.working_beads import lookup
        primary=lookup(self.store.config,args['beads_id'])
        identifier='WORK-'+sha(canonical([self.store.namespace['owner_id'],self.profile,primary['id']]))[:24]
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT project FROM working_cards WHERE profile_id=? AND work_id=?',(self.profile,identifier)).fetchone()
            if old and old[0]!=binding['project']:raise PermissionError('working_project_mismatch')
            db.execute('INSERT INTO working_cards VALUES(?,?,?,?) ON CONFLICT(profile_id,work_id) DO UPDATE SET primary_ref=excluded.primary_ref',
                       (self.profile,identifier,binding['project'],canonical(primary)))
            db.execute('INSERT INTO working_bindings VALUES(?,?,?) ON CONFLICT(profile_id,sid) DO UPDATE SET work_id=excluded.work_id',
                       (self.profile,sid,identifier))
        return self.view(sid)

    def _card(self,sid):
        identifier=self.binding(sid)
        with self.store.db() as db:
            card=db.execute('SELECT * FROM working_cards WHERE profile_id=? AND work_id=?',(self.profile,identifier)).fetchone()
            latest=db.execute('SELECT * FROM working_revisions WHERE profile_id=? AND work_id=? ORDER BY revision DESC LIMIT 1',(self.profile,identifier)).fetchone()
        if card is None or card['project']!=self.store.binding(sid)['project']:raise PermissionError('working_project_mismatch')
        if latest and sha(latest['body'])!=latest['sha256']:raise PermissionError('working_revision_integrity_failed')
        return dict(card),dict(latest) if latest else None

    def sources(self,sid,turn):
        self.store.writable(sid)
        with self.store.db() as db:
            active=db.execute('SELECT turn_id FROM context_admissions WHERE profile_id=? AND sid=?',(self.profile,sid)).fetchone()
            if active is None or (turn is not None and turn!=active[0]):raise PermissionError('working_current_native_turn_required')
            turn=active[0]
            rows=db.execute('SELECT id,turn_id,sha256,length(body) AS characters FROM working_sources WHERE profile_id=? AND sid=? AND turn_id=?',(self.profile,sid,turn)).fetchall()
        return {'sources':[dict(row) for row in rows],'origin':'native_input','coverage':'this native turn only'}

    def _proof(self,sid,item):
        if not isinstance(item,dict) or set(item)!={'id','kind','text','source','visibility','status'}:
            raise ValueError('working_item_contract_invalid')
        if not isinstance(item['id'],str) or not 0<len(item['id'])<=80 or not isinstance(item['kind'],str) or item['kind'] not in KINDS or not isinstance(item['status'],str) or item['status'] not in {'active','resolved_candidate','superseded_candidate'}:
            raise ValueError('working_item_invalid')
        text=item['text'];source=item['source']
        if not isinstance(text,str) or not text or SENSITIVE.search(text) or not isinstance(source,dict) or set(source)!={'id','start','end'} or not isinstance(source['id'],str):
            raise ValueError('working_exact_source_required')
        if type(source['start']) is not int or type(source['end']) is not int or not 0<=source['start']<source['end']:
            raise ValueError('working_source_range_invalid')
        with self.store.db() as db:
            row=db.execute('SELECT * FROM working_sources WHERE profile_id=? AND id=?',(self.profile,source['id'])).fetchone()
            allowed=row and row['project']==self.store.binding(sid)['project']
        if not allowed or source['end']>len(row['body']) or sha(row['body'])!=row['sha256'] or row['body'][source['start']:source['end']]!=text:
            raise PermissionError('working_quote_not_exact_or_not_owned')
        visibility=attributes({'visibility':item['visibility']})['visibility']
        if 'parent' not in visibility['allowed_roles']:raise ValueError('working_parent_visibility_required')
        return item

    @staticmethod
    def _previous(db,operation,input_hash):
        previous=db.execute('SELECT * FROM operations WHERE key=?',(operation,)).fetchone()
        if previous is None:return None
        if previous['input_hash']!=input_hash:raise ValueError('working_idempotency_conflict')
        return {**json.loads(previous['result']),'duplicate':True}

    @staticmethod
    def _source_visibility(items,previous):
        for item in items:
            source=item['source'];roles=set(item['visibility']['allowed_roles'])
            for other in previous+items:
                ref=other['source']
                overlap=(ref['id']==source['id'] and max(ref['start'],source['start'])<min(ref['end'],source['end']))
                if overlap and not roles<=set(other['visibility']['allowed_roles']):
                    raise PermissionError('working_source_visibility_conflict')

    def commit(self,sid,args):
        self.store.writable(sid);card,old=self._card(sid)
        request=args.get('request_id');expected=args.get('expected_revision')
        if not isinstance(request,str) or not 0<len(request)<=128 or type(expected) is not int or expected<0:
            raise ValueError('working_revision_and_request_id_required')
        operation=sha(canonical(['working',self.profile,card['work_id'],sid,request]));input_hash=sha(canonical(args))
        with self.store.db() as db:
            previous=self._previous(db,operation,input_hash)
        if previous:return previous
        if expected!=(old['revision'] if old else 0):raise ValueError('working_revision_conflict')
        items=args.get('items')
        if not isinstance(items,list) or not items:raise ValueError('working_items_required')
        bound=self.store.config.get('working_card_bytes',8192)
        if type(bound) is not int or bound<1:raise ValueError('working_card_bound_invalid')
        if len(canonical(items).encode())>bound:raise PermissionError('required_working_card_exceeds_bound_split_work_do_not_trim')
        checked=[self._proof(sid,item) for item in items]
        indexed={item['id']:item for item in checked}
        if len(indexed)!=len(checked):raise ValueError('working_duplicate_item_id')
        if not any(item['kind']=='goal' for item in checked):raise ValueError('working_goal_required')
        self._source_visibility(checked,json.loads(old['body'])['items'] if old else [])
        if old:
            for item in json.loads(old['body'])['items']:
                new=indexed.get(item['id'])
                if new is None or any(new[key]!=item[key] for key in ['kind','text','source']):
                    raise PermissionError('working_prior_item_must_be_preserved')
                if not set(new['visibility']['allowed_roles'])<=set(item['visibility']['allowed_roles']):
                    raise PermissionError('working_visibility_may_only_narrow')
        from bn_memory.working_beads import lookup
        primary=lookup(self.store.config,json.loads(card['primary_ref'])['id'])
        if primary['status']=='closed':raise PermissionError('working_primary_task_closed')
        if primary['sha256']!=json.loads(card['primary_ref'])['sha256']:raise PermissionError('working_primary_changed_rebind_required')
        with self.store.db() as db:
            receipts={identifier:dict(db.execute('SELECT id,sha256,sid,turn_id,project FROM working_sources WHERE profile_id=? AND id=?',(self.profile,identifier)).fetchone()) for identifier in {item['source']['id'] for item in checked}}
        body=canonical({'contract':'BNWorkingCardV1','horizon':'working','memory_type':'unclassified',
                        'items':checked,'source_provenance':receipts,'primary_ref':primary,
                        'coverage':'explicitly_registered_items_only','semantic_review':'unreviewed','grants_permissions':False})
        if len(body.encode())>bound:raise PermissionError('required_working_card_exceeds_bound_split_work_do_not_trim')
        result={'work_id':card['work_id'],'revision':expected+1,'sha256':sha(body),'semantic_review':'unreviewed','grants_permissions':False}
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=self._previous(db,operation,input_hash)
            if previous:return previous
            bound_now=db.execute('SELECT work_id FROM working_bindings WHERE profile_id=? AND sid=?',(self.profile,sid)).fetchone()
            ref_now=db.execute('SELECT primary_ref FROM working_cards WHERE profile_id=? AND work_id=?',(self.profile,card['work_id'])).fetchone()
            if bound_now is None or bound_now[0]!=card['work_id'] or ref_now is None or ref_now[0]!=card['primary_ref']:
                raise PermissionError('working_binding_or_primary_changed')
            current=db.execute('SELECT COALESCE(MAX(revision),0) FROM working_revisions WHERE profile_id=? AND work_id=?',(self.profile,card['work_id'])).fetchone()[0]
            if current!=expected:raise ValueError('working_revision_conflict')
            db.execute('INSERT INTO working_revisions VALUES(?,?,?,?,?,?)',(self.profile,card['work_id'],expected+1,body,sha(body),time.time()))
            db.execute('INSERT INTO operations VALUES(?,?,?)',(operation,input_hash,canonical(result)))
        return result

    def view(self,sid,revision=None):
        binding=self.store.binding(sid);card,current=self._card(sid)
        if binding['readonly'] and (binding['role']=='unassigned' or not binding['assignment_id']):raise PermissionError('working_child_assignment_required')
        if revision is not None:
            if type(revision) is not int or revision<1:raise ValueError('working_history_revision_invalid')
            with self.store.db() as db:row=db.execute('SELECT * FROM working_revisions WHERE profile_id=? AND work_id=? AND revision=?',(self.profile,card['work_id'],revision)).fetchone()
            if row is None:raise PermissionError('working_revision_unavailable')
            current=dict(row)
        if current and sha(current['body'])!=current['sha256']:raise PermissionError('working_revision_integrity_failed')
        body=json.loads(current['body']) if current else {'items':[],'semantic_review':'unreviewed'}
        visible=[item for item in body['items'] if binding['role'] in item['visibility']['allowed_roles']]
        if binding['role']=='G':visible=[item for item in visible if item['visibility']['evidence_use']!='verification']
        # A historical read cannot revive an item now restricted by the current version.
        if revision is not None:
            latest=self._card(sid)[1]
            allowed={item['id'] for item in json.loads(latest['body'])['items'] if binding['role'] in item['visibility']['allowed_roles'] and not (binding['role']=='G' and item['visibility']['evidence_use']=='verification')}
            visible=[item for item in visible if item['id'] in allowed]
        pending=self.pending(sid,{'page_size':1})
        visible_sources={item['source']['id'] for item in visible}
        receipts={key:value for key,value in body.get('source_provenance',{}).items() if key in visible_sources}
        return {'contract':'BNWorkingViewV1','horizon':'working','memory_type':'unclassified',
                'work_id':card['work_id'],'project':card['project'],
                'revision':current['revision'] if current else 0,'source_revision_sha256':current['sha256'] if current else None,
                'primary_ref':json.loads(card['primary_ref']),'items':visible,'source_provenance':receipts,
                'primary_ref_at_revision':body.get('primary_ref'),
                'primary_changed_since_revision':bool(current and body.get('primary_ref')!=json.loads(card['primary_ref'])),
                'semantic_review':'unreviewed','coverage':'explicitly_registered_items_only',
                'unsettled_actions':{'count':pending['total'],'reader':{'action':'pending_actions'},'retry_permission':False},
                'authority':'working_data_not_system_instructions','grants_permissions':False}

    def history_basis(self,sid):
        view=self.packet(sid)
        return sha(canonical([view['work_id'],view['revision'],view['items']])) if view else None

    def pending(self,sid,args):
        binding=self.store.binding(sid);work_id=self.binding(sid)
        offset=args.get('offset',0);size=args.get('page_size',10)
        if type(offset) is not int or offset<0 or type(size) is not int or not 1<=size<=20:raise ValueError('working_action_page_invalid')
        from bn_memory.recovery import UNSETTLED
        where='w.profile_id=? AND w.work_id=? AND a.status IN (?,?,?,?,?)'
        params=[self.profile,work_id,*UNSETTLED]
        if binding['readonly']:where+=' AND w.sid=?';params.append(sid)
        query=' FROM working_actions w JOIN action_attempts a ON a.profile_id=w.profile_id AND a.nonce=w.nonce WHERE '+where
        with self.store.db() as db:
            count=db.execute('SELECT count(*)'+query,params).fetchone()[0]
            rows=db.execute('SELECT w.sid,a.nonce,a.turn_id,a.call_id,a.tool_name,a.effect,a.input_hash,a.status'+query+' ORDER BY a.created,a.nonce LIMIT ? OFFSET ?',(*params,size,offset)).fetchall()
        return {'actions':[dict(row) for row in rows],'total':count,'has_more':offset+size<count,
                'next_offset':offset+size if offset+size<count else None,'retry_permission':False,
                'coverage':'actions_admitted_while_work_bound'}

    def packet(self,sid):
        with self.store.db() as db:bound=db.execute('SELECT 1 FROM working_bindings WHERE profile_id=? AND sid=?',(self.profile,sid)).fetchone()
        return self.view(sid) if bound else None

    def dispatch(self,sid,args):
        action=args.get('action')
        if action=='bind':return self.bind(sid,args)
        if action=='commit':return self.commit(sid,args)
        if action=='read':return self.view(sid,args.get('revision'))
        if action=='sources':return self.sources(sid,args.get('turn_id'))
        if action=='pending_actions':return self.pending(sid,args)
        raise ValueError('working_action_invalid')
