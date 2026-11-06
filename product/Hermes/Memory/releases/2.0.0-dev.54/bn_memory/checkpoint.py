"""Local exact checkpoints, isolated from retrieval and role-visible memory records."""
import hashlib
import json
import logging
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

    def _committed_goal(self, sid, row):
        """An exact turn input outlives replaceable context-admission revisions.

        A prior checkpoint supplies bytes, never current execution authority.
        Profile, session, turn, input digest and work binding must still match.
        """
        anchors = json.loads(row['anchors'])
        if len(anchors) != 1:
            raise PermissionError('multi_part_goal_restore_not_qualified')
        anchor = anchors[0]
        if self.host.admission.snapshot(sid)[0] != row['binding_hash']:
            raise PermissionError('compression_checkpoint_binding_changed')
        with self.host.store.db() as db:
            commits = db.execute(
                'SELECT * FROM compression_commits WHERE profile_id=? AND sid=? AND turn_id=? ORDER BY rowid DESC',
                (self.host.store.profile, sid, row['turn_id'])).fetchall()
        commit = next((dict(value) for value in commits
                       if value['goal_sha256'] == anchor['sha256']
                       and len(value['goal'].encode()) == anchor['bytes']
                       and digest(value['goal']) == value['goal_sha256']), None)
        if commit is None:
            raise PermissionError('native_compression_commit_required_for_goal_restore')
        payload = self.restore(sid, commit['checkpoint_id'])
        if payload['basis'][0] != row['binding_hash']:
            raise PermissionError('compression_checkpoint_binding_changed')
        captured = payload.get('native_turn')
        if captured is not None and captured != {'turn_id': row['turn_id'], 'anchors': anchors}:
            raise PermissionError('compression_checkpoint_turn_changed')
        return commit

    def native_commit(self,session_id,old_session_id,platform):
        if session_id!=old_session_id:raise PermissionError('compression_rotation_requires_separate_binding_adapter')
        store=self.host.store;binding=store.binding(session_id)
        if bool(binding['readonly'])!=(platform=='subagent'):raise PermissionError('compression_commit_actor_mismatch')
        with store.db() as db:
            cp=db.execute('SELECT * FROM checkpoints WHERE profile_id=? AND sid=? ORDER BY created DESC LIMIT 1',(store.profile,session_id)).fetchone()
            row=db.execute('SELECT * FROM context_admissions WHERE profile_id=? AND sid=?',(store.profile,session_id)).fetchone()
        if not cp or not row:raise PermissionError('native_checkpoint_and_admission_required')
        if row['status'] not in {'ready', 'refresh_required'}:
            raise PermissionError('native_checkpoint_and_admission_required')
        payload=json.loads(cp['payload'])
        if digest(cp['payload'])!=cp['sha256']:
            raise PermissionError('checkpoint_integrity_failed')
        if payload.get('native_turn') != {'turn_id': row['turn_id'], 'anchors': json.loads(row['anchors'])}:
            raise PermissionError('compression_checkpoint_turn_changed')
        if payload['basis'][0] != row['binding_hash'] or payload['basis'][0] != self.host.admission.snapshot(session_id)[0]:
            raise PermissionError('compression_checkpoint_binding_changed')
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
                try:
                    matched = self._committed_goal(session_id, row)['goal']
                except PermissionError as exc:
                    if str(exc) != 'native_compression_commit_required_for_goal_restore':
                        raise
            if matched is None:raise PermissionError('exact_original_goal_missing_from_checkpoint')
            goals.append(matched)
        if len(goals)!=1:raise PermissionError('multi_part_goal_restore_not_qualified')
        goal=goals[0]
        with store.db() as db:db.execute('INSERT INTO compression_commits VALUES(?,?,?,?,?,?,?) ON CONFLICT(profile_id,sid,token) DO UPDATE SET checkpoint_id=excluded.checkpoint_id',
            (store.profile,session_id,row['turn_id'],row['token'],cp['id'],goal,digest(goal)))

    def restore_goal(self,sid,turn_id,request):
        from bn_memory.admission import last_user,text_parts
        row=self.host.admission.row(sid,turn_id,allow_refresh_required=True)
        try:self.host.admission.check_anchor(row,request);return
        except PermissionError as exc:
            if str(exc)!='current_input_anchor_mismatch':raise
        commit = self._committed_goal(sid, row)
        target=last_user(request)
        if isinstance(target.get('content'),str):target['content']=commit['goal']+'\n'+target['content']
        else:target['content'].insert(0,{'type':'input_text' if 'input' in request else 'text','text':commit['goal']})
        self.host.admission.check_anchor(row,request)
        logging.getLogger('bnn.context_continuity').info(
            'BN_GOAL_RESTORE turn=%s source=committed_checkpoint admission_rotated=%s',
            digest(turn_id)[:16], commit['token'] != row['token'])

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
        with self.host.store.db() as db:
            turn = db.execute('SELECT turn_id,anchors FROM context_admissions WHERE profile_id=? AND sid=?',
                              (self.host.store.profile, source.session_id)).fetchone()
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
                             'basis': snapshot,
                             'native_turn': {'turn_id': turn['turn_id'], 'anchors': json.loads(turn['anchors'])} if turn else None,
                             'messages': source.messages, 'evidence_messages': evidence_messages,
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
