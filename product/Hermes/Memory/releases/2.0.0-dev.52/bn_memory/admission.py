"""Persistent native-turn receipts. Preparation may fail; terminal admission never falls back."""
import hashlib
import hmac
import json
from pathlib import Path
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def install(connection):
    from bn_memory.control_schema import install as create
    create(connection, 'context_admissions', 'session_policy', 'launch_grants')
    connection.execute("INSERT INTO meta VALUES('context_admission_contract','2')")


def text_parts(content):
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [part['text'] for part in content if isinstance(part, dict) and isinstance(part.get('text'), str)]
    return []


def anchors_for(content):
    if isinstance(content,list) and any(not isinstance(part,dict) or not isinstance(part.get('text'),str) for part in content):
        raise PermissionError('non_text_input_anchor_not_implemented')
    parts = text_parts(content)
    if not parts:
        raise PermissionError('input_anchor_unsupported')
    return [{'bytes': len(part.encode()), 'sha256': digest(part)} for part in parts]


def last_user(request):
    rows = request.get('messages', request.get('input', []))
    if not isinstance(rows, list):
        raise PermissionError('native_context_envelope_required')
    row = next((item for item in reversed(rows) if isinstance(item, dict) and item.get('role') == 'user'), None)
    if row is None:
        raise PermissionError('native_context_envelope_required')
    return row


class Admission:
    def __init__(self, store, config, profile_home,config_path=None):
        self.store, self.config = store, config
        self.profile_home = str(Path(profile_home).resolve())
        self.config_path=Path(config_path).resolve() if config_path else None
        self.loaded_settings_hash=hashlib.sha256(self.config_path.read_bytes()).hexdigest() if self.config_path else None
        key_path=Path(config['host_key'])
        if key_path.is_symlink():
            raise PermissionError('unsafe_context_signing_key')
        self.key = key_path.read_bytes()
        if len(self.key) < 32:
            raise PermissionError('context_signing_key_invalid')

    def profile_hash(self):
        from hermes_constants import get_hermes_home
        if str(get_hermes_home().resolve()) != self.profile_home:
            raise PermissionError('context_profile_mismatch')
        hashes = {'profile_home':self.profile_home}
        if self.config_path:
            current=hashlib.sha256(self.config_path.read_bytes()).hexdigest()
            if current!=self.loaded_settings_hash:raise PermissionError('runtime_settings_changed_requires_reload')
            hashes['runtime_settings']=current
        for name in ['config.yaml', 'execution-controls.json']:
            path = Path(self.profile_home) / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 1048576:
                raise PermissionError('unsafe_profile_policy')
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest(canonical(hashes))

    def policy(self, sid, create=False):
        binding = self.store.binding(sid)
        while binding['parent']:
            binding = self.store.binding(binding['parent'])
        with self.store.db() as connection:
            row = connection.execute('SELECT * FROM session_policy WHERE profile_id=? AND sid=?', (self.store.profile,binding['sid'])).fetchone()
            if create and row is None:
                connection.execute("INSERT OR IGNORE INTO session_policy VALUES(?,1,'auto',1,1,1,?)", (binding['sid'],self.store.profile))
                row = connection.execute('SELECT * FROM session_policy WHERE profile_id=? AND sid=?', (self.store.profile,binding['sid'])).fetchone()
        if row is None:
            raise PermissionError('session_policy_required')
        value=dict(row)
        if value['gsd_mode'] not in {'auto','off'} or type(value['research_enabled']) is not int or value['research_enabled'] not in {0,1}:
            raise PermissionError('session_policy_corrupt')
        for key in ['revision','gsd_revision','research_revision']:
            if type(value[key]) is not int or value[key]<1 or value[key]>value['revision']:
                raise PermissionError('session_policy_corrupt')
        return value

    def revise_policy(self, sid, expected, gsd_mode, research_enabled):
        self.store.writable(sid)
        if gsd_mode not in {'auto', 'off'} or type(research_enabled) is not bool:
            raise ValueError('session_policy_invalid')
        self.policy(sid, create=True)
        with self.store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            previous=dict(connection.execute('SELECT * FROM session_policy WHERE profile_id=? AND sid=?',(self.store.profile,sid)).fetchone())
            if previous['revision']!=expected:
                raise ValueError('policy_revision_conflict')
            gsd_changed=previous['gsd_mode']!=gsd_mode
            research_changed=previous['research_enabled']!=int(research_enabled)
            if gsd_changed or research_changed:
                connection.execute('UPDATE session_policy SET revision=?,gsd_mode=?,research_enabled=?,gsd_revision=?,research_revision=? WHERE profile_id=? AND sid=?',
                    (expected+1,gsd_mode,int(research_enabled),previous['gsd_revision']+int(gsd_changed),
                     previous['research_revision']+int(research_changed),self.store.profile,sid))
        return self.policy(sid)

    def snapshot(self, sid):
        binding = self.store.binding(sid)
        if binding['readonly'] and (not binding['assignment_id'] or binding['role'] == 'unassigned'):
            raise PermissionError('child_assignment_required')
        fields = {key: binding[key] for key in ['profile_id','sid','project', 'task', 'parent', 'readonly', 'role', 'purpose', 'assignment_id']}
        identity=getattr(self,'identity_reference',None)
        if identity is not None:fields['identity_reference']=identity(sid)
        policy=self.policy(sid)
        effective_revision=policy['revision']
        with self.store.db() as connection:
            marker=connection.execute("SELECT value FROM meta WHERE key='source_visibility_contract'").fetchone()
            if not marker or marker[0]!='1':raise PermissionError('source_visibility_contract_unsupported')
            from bn_memory.source_policy_scope import check
            check(self.store,connection,binding)
            fields['source_admission_scope_contract']=1
            contract=connection.execute("SELECT value FROM meta WHERE key='context_admission_contract'").fetchone()
            if contract is None or contract[0]!='2':raise PermissionError('context_admission_contract_unsupported')
            if binding['readonly']:
                grant=connection.execute("SELECT * FROM launch_grants WHERE profile_id=? AND id=? AND child_sid=? AND state='admitted'",
                                         (self.store.profile,binding['assignment_id'],sid)).fetchone()
                if grant is None or grant['parent_sid']!=binding['parent'] or grant['role']!=binding['role']:
                    raise PermissionError('native_assignment_receipt_required')
                module=grant['module']
                if binding['role'] in {'G','S','D'} and module!='gsd':raise PermissionError('assignment_module_invalid')
                if module=='gsd':
                    if policy['gsd_mode']=='off':raise PermissionError('gsd_disabled_for_session')
                    effective_revision=policy['gsd_revision']
                elif module=='research':
                    if not policy['research_enabled']:raise PermissionError('research_disabled_for_session')
                    effective_revision=policy['research_revision']
                elif module=='base':effective_revision=1
                else:raise PermissionError('assignment_module_invalid')
            epoch = connection.execute("SELECT COALESCE(MAX(a.seq),0) FROM audit a JOIN records r ON a.record_id=r.id AND a.revision=r.revision WHERE a.event IN ('record','retract') AND r.scope IN (?,?,?)",
                                       self.store.scopes(binding)).fetchone()[0]
        return digest(canonical(fields)), self.profile_hash(), effective_revision, epoch

    def begin(self, sid, turn_id, content, query):
        if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 512:
            raise PermissionError('native_turn_id_required')
        self.policy(sid, create=True)
        from bn_memory.source_policy_scope import begin as begin_sources
        with self.store.db() as connection:begin_sources(self.store,connection,self.store.binding(sid))
        binding, profile, policy, epoch = self.snapshot(sid)
        token = uuid.uuid4().hex
        with self.store.db() as connection:
            connection.execute('INSERT OR REPLACE INTO context_admissions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid, turn_id, token, 'preparing', binding, profile, policy, epoch,
                 canonical(anchors_for(content)), query, None, None, '[]',self.store.profile))
            connection.execute('UPDATE sessions SET context=NULL,turn=NULL WHERE profile_id=? AND sid=?', (self.store.profile,sid))
        return token

    def invalidate(self,sid):
        with self.store.db() as connection:
            connection.execute("UPDATE context_admissions SET status='failed' WHERE profile_id=? AND sid=?",(self.store.profile,sid))

    def row(self, sid, turn_id, *, allow_refresh_required=False):
        if not turn_id:
            raise PermissionError('native_turn_id_required')
        with self.store.db() as connection:
            row = connection.execute('SELECT * FROM context_admissions WHERE profile_id=? AND sid=?', (self.store.profile,sid)).fetchone()
        allowed = {'ready', 'refresh_required'} if allow_refresh_required else {'ready'}
        if row is None or row['turn_id'] != turn_id or row['status'] not in allowed:
            raise PermissionError('current_turn_context_not_ready')
        return dict(row)

    def publish(self, sid, token, context):
        with self.store.db() as connection:
            row = connection.execute('SELECT * FROM context_admissions WHERE profile_id=? AND sid=? AND token=? AND status=\'preparing\'', (self.store.profile,sid,token)).fetchone()
        if row is None:
            raise PermissionError('context_preparation_superseded')
        row = dict(row)
        if self.snapshot(sid) != (row['binding_hash'], row['profile_hash'], row['policy_revision'], row['data_epoch']):
            raise PermissionError('context_basis_changed_during_preparation')
        from bn_memory.packet import build
        context=build(self,sid,row,context)
        with self.store.db() as connection:
            connection.execute('UPDATE sessions SET context=? WHERE profile_id=? AND sid=?',(context,self.store.profile,sid))
        receipt = {key: row[key] for key in ['profile_id','sid', 'turn_id', 'token', 'binding_hash', 'profile_hash', 'policy_revision', 'data_epoch', 'anchors']}
        signature = hmac.new(self.key, canonical([receipt, context]).encode(), hashlib.sha256).hexdigest()
        envelope = '<BN_CONTEXT_ADMISSION signature="' + signature + '">\n' + canonical(receipt) + '\n' + context + '\n</BN_CONTEXT_ADMISSION>'
        with self.store.db() as connection:
            changed = connection.execute("UPDATE context_admissions SET status='ready',context_hash=?,envelope=? WHERE profile_id=? AND sid=? AND token=? AND status='preparing'",
                                          (digest(context), envelope, self.store.profile,sid,token)).rowcount
        if changed != 1:
            raise PermissionError('context_preparation_superseded')
        return envelope

    def fail(self, sid, token):
        with self.store.db() as connection:
            connection.execute("UPDATE context_admissions SET status='failed' WHERE profile_id=? AND sid=? AND token=?", (self.store.profile,sid,token))

    @staticmethod
    def check_anchor(row, request):
        candidates = [part.encode() for part in text_parts(last_user(request).get('content'))]
        for anchor in json.loads(row['anchors']):
            if not any(len(value) >= anchor['bytes'] and hashlib.sha256(value[:anchor['bytes']]).hexdigest() == anchor['sha256'] for value in candidates):
                raise PermissionError('current_input_anchor_mismatch')

    def ready(self, sid, turn_id, request=None, refresh=False):
        row = self.row(sid, turn_id, allow_refresh_required=refresh)
        if request is not None:
            self.check_anchor(row, request)
        current = self.snapshot(sid)
        if current[:3] != (row['binding_hash'], row['profile_hash'], row['policy_revision']):
            raise PermissionError('context_role_profile_or_policy_changed')
        if row['status'] == 'refresh_required' or current[3] != row['data_epoch']:
            if not refresh:
                raise PermissionError('context_data_revision_changed')
            token = uuid.uuid4().hex
            retired = json.loads(row['retired']) + [row['envelope']]
            with self.store.db() as connection:
                changed = connection.execute("UPDATE context_admissions SET status='preparing',token=?,data_epoch=?,context_hash=NULL,envelope=NULL,retired=? WHERE profile_id=? AND sid=? AND token=? AND status=?",
                                              (token, current[3], canonical(retired), self.store.profile,sid,row['token'],row['status'])).rowcount
                if changed != 1:
                    raise PermissionError('context_refresh_superseded')
                connection.execute('UPDATE sessions SET context=NULL,turn=NULL WHERE profile_id=? AND sid=?', (self.store.profile,sid))
            return {**row, 'status': 'preparing', 'token': token, 'data_epoch': current[3], 'retired': canonical(retired)}
        context = self.store.binding(sid)['context']
        if not context or digest(context) != row['context_hash']:
            raise PermissionError('prepared_context_changed')
        receipt = {key: row[key] for key in ['profile_id','sid', 'turn_id', 'token', 'binding_hash', 'profile_hash', 'policy_revision', 'data_epoch', 'anchors']}
        signature = hmac.new(self.key, canonical([receipt, context]).encode(), hashlib.sha256).hexdigest()
        expected = '<BN_CONTEXT_ADMISSION signature="' + signature + '">\n' + canonical(receipt) + '\n' + context + '\n</BN_CONTEXT_ADMISSION>'
        if not hmac.compare_digest(expected.encode(), row['envelope'].encode()):
            raise PermissionError('context_receipt_integrity_failed')
        return row

    def validate(self, sid, turn_id, request, api_request_id, retry_count=0):
        if not isinstance(api_request_id, str) or not api_request_id:
            raise PermissionError('native_api_request_id_required')
        if len(canonical({k: v for k, v in request.items() if k not in {'timeout', 'http_client'}}).encode()) > self.config.get('max_request_bytes', 8388608):
            raise PermissionError('native_request_size_exceeded')
        row = self.ready(sid, turn_id, request)
        parts = text_parts(last_user(request).get('content'))
        if not any(row['envelope'] in part for part in parts):
            raise PermissionError('current_context_receipt_not_delivered')
        if any(old in part for old in json.loads(row['retired']) for part in parts):
            raise PermissionError('superseded_current_turn_context_delivered')
        if type(retry_count) is not int or retry_count<0:raise PermissionError('native_attempt_number_required')
        receipt={'contract':'BNContextAttemptV1','profile_id':self.store.profile,'session_id':sid,'step_id':turn_id,
                 'attempt_id':api_request_id+'.'+str(retry_count),'packet_id':row['token'],
                 'request_hash':digest(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}})),
                 'request_bytes':len(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}}).encode()),
                 'basis':[row['binding_hash'],row['profile_hash'],row['policy_revision'],row['data_epoch']],
                 'status':'this_controller_admitted_not_dispatch_or_completion','provider_tokens':None}
        receipt['request_model']=request.get('model')
        receipt['request_reasoning_effort']=(request.get('reasoning') or {}).get('effort')
        with self.store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT OR IGNORE INTO context_attempts VALUES(?,?,?,?,?,?,?)',
                               (self.store.profile,sid,turn_id,api_request_id,retry_count,receipt['request_hash'],canonical(receipt)))
        return row
