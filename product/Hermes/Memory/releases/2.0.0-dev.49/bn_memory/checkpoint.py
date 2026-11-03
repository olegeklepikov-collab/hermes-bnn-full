"""Local exact checkpoints, isolated from retrieval and role-visible memory records."""
import hashlib
import json
import time
import uuid

from bn_memory.admission import canonical, digest


def install(connection):
    from bn_memory.control_schema import install as create
    create(connection, 'auxiliary_admissions', 'checkpoints')
    connection.execute("INSERT INTO meta VALUES('auxiliary_checkpoint_contract','1')")


class Checkpoints:
    def __init__(self, host):
        self.host = host
        with host.store.db() as db:db.execute('CREATE TABLE IF NOT EXISTS compression_commits(profile_id TEXT,sid TEXT,turn_id TEXT,token TEXT,checkpoint_id TEXT,goal TEXT,goal_sha256 TEXT,PRIMARY KEY(profile_id,sid,token))')

    def native_commit(self,session_id,old_session_id,platform):
        if session_id!=old_session_id:raise PermissionError('compression_rotation_requires_separate_binding_adapter')
        store=self.host.store;binding=store.binding(session_id)
        if bool(binding['readonly'])!=(platform=='subagent'):raise PermissionError('compression_commit_actor_mismatch')
        with store.db() as db:
            cp=db.execute('SELECT * FROM checkpoints WHERE profile_id=? AND sid=? ORDER BY created DESC LIMIT 1',(store.profile,session_id)).fetchone()
            row=db.execute('SELECT * FROM context_admissions WHERE profile_id=? AND sid=?',(store.profile,session_id)).fetchone()
        if not cp or not row:raise PermissionError('native_checkpoint_and_admission_required')
        payload=json.loads(cp['payload'])
        if digest(cp['payload'])!=cp['sha256'] or canonical(payload['basis'])!=canonical(self.host.admission.snapshot(session_id)):raise PermissionError('compression_checkpoint_basis_changed')
        from bn_memory.admission import text_parts
        goals=[]
        for anchor in json.loads(row['anchors']):
            matched=None
            for message in payload['messages']:
                if message.get('role')!='user':continue
                for part in text_parts(message.get('content')):
                    raw=part.encode()
                    if len(raw)>=anchor['bytes'] and hashlib.sha256(raw[:anchor['bytes']]).hexdigest()==anchor['sha256']:matched=raw[:anchor['bytes']].decode()
            if matched is None:
                with store.db() as db:prior=db.execute('SELECT goal FROM compression_commits WHERE profile_id=? AND sid=? AND token=?',(store.profile,session_id,row['token'])).fetchone()
                if prior and digest(prior[0])==anchor['sha256']:matched=prior[0]
            if matched is None:raise PermissionError('exact_original_goal_missing_from_checkpoint')
            goals.append(matched)
        if len(goals)!=1:raise PermissionError('multi_part_goal_restore_not_qualified')
        goal=goals[0]
        with store.db() as db:db.execute('INSERT INTO compression_commits VALUES(?,?,?,?,?,?,?) ON CONFLICT(profile_id,sid,token) DO UPDATE SET checkpoint_id=excluded.checkpoint_id',
            (store.profile,session_id,row['turn_id'],row['token'],cp['id'],goal,digest(goal)))

    def restore_goal(self,sid,turn_id,request):
        from bn_memory.admission import last_user,text_parts
        row=self.host.admission.row(sid,turn_id)
        try:self.host.admission.check_anchor(row,request);return
        except PermissionError as exc:
            if str(exc)!='current_input_anchor_mismatch':raise
        with self.host.store.db() as db:commit=db.execute('SELECT * FROM compression_commits WHERE profile_id=? AND sid=? AND token=? AND turn_id=?',(self.host.store.profile,sid,row['token'],turn_id)).fetchone()
        if not commit or digest(commit['goal'])!=commit['goal_sha256']:raise PermissionError('native_compression_commit_required_for_goal_restore')
        self.restore(sid,commit['checkpoint_id'])
        target=last_user(request)
        if isinstance(target.get('content'),str):target['content']=commit['goal']+'\n'+target['content']
        else:target['content'].insert(0,{'type':'input_text' if 'input' in request else 'text','text':commit['goal']})
        self.host.admission.check_anchor(row,request)

    def save(self, source, evidence_messages):
        admission = self.host.admission
        if source.profile_home != admission.profile_home:
            raise PermissionError('checkpoint_profile_mismatch')
        binding = self.host.store.binding(source.session_id)
        if (binding['parent'] or '') != source.parent_session_id:
            raise PermissionError('checkpoint_parent_mismatch')
        if bool(binding['readonly']) != (source.platform == 'subagent'):
            raise PermissionError('checkpoint_actor_mismatch')
        snapshot = admission.snapshot(source.session_id)
        from bn_memory.working import Working
        working=Working(self.host.store).packet(source.session_id)
        payload = canonical({'contract':'WorkCheckpointV1', 'version': 1,
                             'goals_constraints':{'source':'exact native messages below','semantic_extraction':'not_performed'},
                             'open_obligations':working,
                             'effects_and_jobs': self.control_state(source.session_id),
                             'document_coverage':'not_inferred_from_transcript',
                             'external_snapshot':'not_atomic; local state references only',
                             'next_safe_action':'Validate current policy, identity, work and effect state before continuation.', 'session': binding, 'policy': admission.policy(source.session_id),
                             'working':working,'working_basis':Working(self.host.store).history_basis(source.session_id),
                             'identity_reference': self.host.identity.reference(source.session_id) if self.host.identity else None,
                             'basis': snapshot, 'messages': source.messages, 'evidence_messages': evidence_messages,
                             'provenance': 'native_pre_compression_input',
                             'semantic_review': 'not_performed'})
        identifier = 'checkpoint-' + uuid.uuid4().hex
        checksum = digest(payload)
        with self.host.store.db() as connection:
            connection.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                               (identifier, source.session_id, checksum, payload, time.time(),self.host.store.profile))
        # A separate connection verifies the committed representation before acknowledging.
        restored = self.restore(source.session_id, identifier)
        if digest(canonical(restored)) != checksum or admission.snapshot(source.session_id) != snapshot:
            raise PermissionError('checkpoint_verification_failed')
        return canonical({'checkpoint_id': identifier, 'sha256': checksum, 'message_count': len(source.messages),
                          'source': 'native_full_transcript', 'semantic_review': 'not_performed',
                          'instruction': 'Retain constraints, changed decisions and open obligations. Original history is preserved by this reference.'})

    def control_state(self,sid):
        with self.host.store.db() as db:
            attempts=[dict(row) for row in db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND sid=?',(self.host.store.profile,sid))]
        shared={}
        if self.host.config.get('w3_enabled'):
            root=self.host.store.binding(sid)
            while root['parent']:root=self.host.store.binding(root['parent'])
            with self.host.store.db() as db:shared['module_attempts']=[dict(row) for row in db.execute('SELECT id,module,bead,input_hash,state FROM module_attempts WHERE profile_id=? AND sid=?',(self.host.store.profile,root['sid']))]
            shared['resource']=self.host.accounting.status(sid)
        return {'native_action_attempts':attempts,'shared_W3_state':shared,'external_jobs':'module receipts captured; remote provider jobs remain adapter-owned',
                'spent_resource':'module-owned ledger; not reset by this checkpoint',
                'active_gsd_generation':'not_inferred; must be checked by GSD before resume'}

    def restore(self, sid, identifier):
        self.host.admission.profile_hash()
        from bn_memory.recovery import Recovery
        return Recovery(self.host.store).load(sid,identifier)

    def child_adapter(self, source, evidence_messages):
        return self.save(source, evidence_messages)
