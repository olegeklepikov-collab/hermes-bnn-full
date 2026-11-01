"""Separate identity ledger, signed decisions, durable one-profile application and session pins."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import re
from jsonschema import Draft202012Validator,ValidationError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from .io import RESERVED, digest, encoded, locked, read_regular, save_new, sync_directory

BUILDER='identity-0.2/native-soul-slot-1'


def initialize(root,*,instance_id,agent_id,profiles,legacy_observation=None):
    uuid.UUID(instance_id)
    if not isinstance(agent_id,str) or not 1<=len(agent_id)<=128:raise ValueError('explicit_agent_id_required')
    if any(not isinstance(name,str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',name) is None for name in profiles):
        raise ValueError('explicit_profile_ids_required')
    root=Path(root).resolve();root.mkdir(mode=0o700)
    bindings={name:str(Path(path).resolve()) for name,path in profiles.items()}
    if not bindings or any(not name or Path(path).name!='SOUL.md' for name,path in bindings.items()):
        raise ValueError('explicit_soul_profile_bindings_required')
    sources={name:read_regular(path) for name,path in bindings.items()}
    if any(not raw.decode('utf-8').strip() for raw in sources.values()):raise ValueError('nonempty_utf8_identity_required')
    private=Ed25519PrivateKey.generate()
    save_new(root/'owner.key',private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))
    public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    policy={'schema':2,'version':'0.2.0','instance_id':instance_id,'agent_id':agent_id,
            'profiles':bindings,'owner_public_key':public,'deep_identity':dict.fromkeys(RESERVED),
            'legacy_observation':legacy_observation,'baseline_policy':'explicit_observed_compatibility_only'}
    save_new(root/'policy.json',encoded(policy))
    connection=sqlite3.connect(root/'identity.sqlite')
    try:
        connection.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE revisions(id TEXT PRIMARY KEY,profile TEXT NOT NULL,kind TEXT NOT NULL,parent TEXT,
            content BLOB NOT NULL,sha256 TEXT NOT NULL,manifest TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE active(profile TEXT PRIMARY KEY,revision TEXT NOT NULL,generation INTEGER NOT NULL);
        CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,profile TEXT NOT NULL,revision TEXT NOT NULL,
            details TEXT NOT NULL,previous_hash TEXT,event_hash TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE intents(id TEXT PRIMARY KEY,profile TEXT NOT NULL,old_revision TEXT NOT NULL,
            old_sha256 TEXT NOT NULL,target_revision TEXT NOT NULL,generation INTEGER NOT NULL,
            receipt TEXT NOT NULL,status TEXT NOT NULL);
        CREATE TABLE pins(profile TEXT NOT NULL,sid TEXT NOT NULL,revision TEXT NOT NULL,role TEXT NOT NULL,
            parent_sid TEXT NOT NULL,view TEXT NOT NULL,view_sha256 TEXT NOT NULL,reference TEXT NOT NULL,
            PRIMARY KEY(profile,sid));''')
        connection.commit()
    finally:connection.close()
    (root/'identity.sqlite').chmod(0o600)
    store=Store(root)
    with store.db() as connection:
        for profile,raw in sources.items():
            revision=store._revision(connection,profile,raw,'observed',None,'existing native file; not approval')
            connection.execute('INSERT INTO active VALUES(?,?,1)',(profile,revision))
            store._event(connection,'observed_compatibility_baseline',profile,revision,{})
    if any(read_regular(bindings[name])!=raw for name,raw in sources.items()):raise RuntimeError('native_changed_during_observation')
    sync_directory(root)
    return store.status()


class Store:
    def __init__(self,root):
        self.root=Path(root).resolve(strict=True)
        self.policy=json.loads(read_regular(self.root/'policy.json'))
        if self.policy['schema']!=2 or self.policy['deep_identity']!=dict.fromkeys(RESERVED):raise ValueError('identity_contract_not_supported')
        self.public=Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.policy['owner_public_key']))
        schema=json.loads(read_regular(Path(__file__).resolve().parents[1]/'identity.schema.json'))
        self.schema=Draft202012Validator(schema)

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.root/'identity.sqlite',timeout=3);connection.row_factory=sqlite3.Row
        try:
            connection.execute('PRAGMA synchronous=FULL');yield connection;connection.commit()
        except BaseException:connection.rollback();raise
        finally:connection.close()

    def _event(self,connection,kind,profile,revision,details):
        previous=connection.execute('SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        previous=previous[0] if previous else None;now=time.time()
        checksum=digest(encoded([kind,profile,revision,details,previous,now]))
        connection.execute('INSERT INTO events(kind,profile,revision,details,previous_hash,event_hash,created) VALUES(?,?,?,?,?,?,?)',
                           (kind,profile,revision,encoded(details).decode(),previous,checksum,now))

    def _revision(self,connection,profile,raw,kind,parent,reason):
        if profile not in self.policy['profiles'] or not raw.decode('utf-8').strip():raise ValueError('identity_profile_and_content_required')
        if 'BN_IDENTITY_VIEW' in raw.decode('utf-8'):raise ValueError('reserved_identity_framing_forbidden')
        revision='ID-'+uuid.uuid4().hex;now=time.time()
        manifest={'instance_id':self.policy['instance_id'],'agent_id':self.policy['agent_id'],'profile':profile,
                  'revision':revision,'parent':parent,'kind':kind,'source_sha256':digest(raw),'reason':reason,
                  'builder':BUILDER,'deep_identity':dict.fromkeys(RESERVED)}
        connection.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)',
            (revision,profile,kind,parent,raw,digest(raw),encoded(manifest).decode(),digest(encoded(manifest)),kind,now))
        return revision

    def revision(self,revision):
        with self.db() as connection:row=connection.execute('SELECT * FROM revisions WHERE id=?',(revision,)).fetchone()
        if row is None:raise PermissionError('identity_revision_not_found')
        row=dict(row);manifest=json.loads(row['manifest'])
        try:self.schema.validate(manifest)
        except ValidationError as exc:raise PermissionError('identity_manifest_schema_invalid') from exc
        if digest(bytes(row['content']))!=row['sha256'] or digest(encoded(manifest))!=row['manifest_sha256']:
            raise PermissionError('identity_revision_integrity_failed')
        if manifest['deep_identity']!=dict.fromkeys(RESERVED) or manifest['instance_id']!=self.policy['instance_id'] or manifest['profile']!=row['profile'] or manifest['revision']!=revision or manifest['source_sha256']!=row['sha256'] or manifest['agent_id']!=self.policy['agent_id']:
            raise PermissionError('identity_lineage_mismatch')
        return row

    def active(self,profile,verify_native=True):
        if profile not in self.policy['profiles']:raise PermissionError('identity_profile_not_bound')
        with self.db() as connection:
            row=connection.execute('SELECT * FROM active WHERE profile=?',(profile,)).fetchone()
            pending=connection.execute("SELECT id FROM intents WHERE profile=? AND status='prepared'",(profile,)).fetchone()
        if row is None or pending is not None:raise PermissionError('identity_application_recovery_required')
        value=dict(row);revision=self.revision(value['revision'])
        if revision['status']=='cancelled':raise PermissionError('identity_revision_revoked')
        if revision['status'] not in {'observed','accepted'}:raise PermissionError('identity_active_revision_not_permitted')
        if revision['status']=='accepted':self._accepted(revision)
        if verify_native and digest(read_regular(self.policy['profiles'][profile]))!=revision['sha256']:
            raise PermissionError('native_identity_drift')
        return {**value,'source_sha256':revision['sha256']}

    def propose(self,profile,content,*,expected_revision,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('proposal_reason_required')
        with locked(self.root):
            if self.active(profile)['revision']!=expected_revision:raise ValueError('identity_revision_conflict')
            with self.db() as connection:
                revision=self._revision(connection,profile,content,'proposed',expected_revision,reason)
                self._event(connection,'proposed',profile,revision,{})
        return revision

    def verify_receipt(self,receipt,decision):
        payload=receipt['payload'];self.public.verify(bytes.fromhex(receipt['signature']),encoded(payload))
        row=self.revision(payload['revision'])
        expected={'instance_id':self.policy['instance_id'],'decision':decision,'profile':row['profile'],
                  'manifest_sha256':row['manifest_sha256'],'source_sha256':row['sha256']}
        if any(payload.get(key)!=value for key,value in expected.items()):raise PermissionError('owner_identity_receipt_mismatch')
        return row

    def accept(self,receipt):
        with locked(self.root):
            row=self.verify_receipt(receipt,'accept')
            if row['status'] not in {'observed','proposed'} or receipt['payload']['expected_status']!=row['status']:
                raise ValueError('identity_accept_state_conflict')
            with self.db() as connection:
                connection.execute("UPDATE revisions SET status='accepted' WHERE id=?",(row['id'],))
                self._event(connection,'accepted',row['profile'],row['id'],receipt)

    def cancel(self,receipt):
        with locked(self.root):
            row=self.verify_receipt(receipt,'cancel')
            if self.active(row['profile'])['revision']==row['id']:raise ValueError('active_identity_requires_explicit_replacement')
            if row['status']=='cancelled' or receipt['payload']['expected_status']!=row['status']:raise ValueError('identity_cancel_state_conflict')
            with self.db() as connection:
                connection.execute("UPDATE revisions SET status='cancelled' WHERE id=?",(row['id'],))
                self._event(connection,'cancelled',row['profile'],row['id'],receipt)

    def _accepted(self,row):
        if row['status']!='accepted':raise PermissionError('accepted_identity_revision_required')
        with self.db() as connection:
            event=connection.execute("SELECT details FROM events WHERE revision=? AND kind='accepted' ORDER BY seq DESC LIMIT 1",(row['id'],)).fetchone()
        if event is None:raise PermissionError('owner_acceptance_receipt_required')
        self.verify_receipt(json.loads(event[0]),'accept')

    def _replace_native(self,path,raw):
        temporary=Path(path).with_name('.identity-'+uuid.uuid4().hex)
        try:
            save_new(temporary,raw);os.replace(temporary,path);sync_directory(Path(path).parent)
        finally:temporary.unlink(missing_ok=True)

    def _complete(self,intent):
        row=self.revision(intent['target_revision']);receipt=json.loads(intent['receipt'])
        self._check_intent(intent);self._accepted(row)
        if digest(read_regular(self.policy['profiles'][intent['profile']]))!=row['sha256']:
            raise PermissionError('native_identity_not_replaced_as_approved')
        with self.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current=connection.execute('SELECT * FROM active WHERE profile=?',(intent['profile'],)).fetchone()
            if current['revision']!=intent['old_revision'] or current['generation']!=intent['generation']:
                raise ValueError('identity_application_generation_conflict')
            connection.execute('UPDATE active SET revision=?,generation=generation+1 WHERE profile=?',(row['id'],intent['profile']))
            connection.execute("UPDATE intents SET status='complete' WHERE id=?",(intent['id'],))
            self._event(connection,'applied',intent['profile'],row['id'],{'intent_id':intent['id'],'receipt':receipt})

    def _check_intent(self,intent):
        receipt=json.loads(intent['receipt']);payload=receipt['payload'];decision=payload['decision']
        if decision not in {'apply','rollback'}:raise PermissionError('identity_application_decision_required')
        self.verify_receipt(receipt,decision)
        if payload['profile']!=intent['profile'] or payload['revision']!=intent['target_revision'] or payload['expected_revision']!=intent['old_revision'] or payload['expected_sha256']!=intent['old_sha256']:
            raise PermissionError('identity_intent_receipt_mismatch')

    def apply(self,receipt):
        with locked(self.root):
            decision=receipt['payload']['decision']
            if decision not in {'apply','rollback'}:raise PermissionError('identity_application_decision_required')
            row=self.verify_receipt(receipt,decision);self._accepted(row)
            current=self.active(row['profile']);payload=receipt['payload']
            with self.db() as connection:
                used=connection.execute("SELECT id FROM intents WHERE json_extract(receipt,'$.payload.nonce')=?",(payload['nonce'],)).fetchone()
            if used is not None:raise PermissionError('owner_identity_receipt_already_used')
            if current['revision']!=payload['expected_revision'] or current['source_sha256']!=payload['expected_sha256']:
                raise ValueError('identity_revision_or_hash_conflict')
            intent={'id':'IA-'+uuid.uuid4().hex,'profile':row['profile'],'old_revision':current['revision'],
                    'old_sha256':current['source_sha256'],'target_revision':row['id'],'generation':current['generation'],
                    'receipt':encoded(receipt).decode(),'status':'prepared'}
            with self.db() as connection:
                connection.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?)',tuple(intent.values()))
                self._event(connection,'application_prepared',row['profile'],row['id'],{'intent_id':intent['id']})
            if digest(read_regular(self.policy['profiles'][row['profile']]))!=current['source_sha256']:
                raise PermissionError('native_identity_changed_before_replace')
            self._replace_native(self.policy['profiles'][row['profile']],bytes(row['content']))
            self._complete(intent)
            return intent['id']

    def recover(self,identifier):
        with locked(self.root):
            with self.db() as connection:row=connection.execute('SELECT * FROM intents WHERE id=?',(identifier,)).fetchone()
            if row is None or row['status']!='prepared':raise ValueError('pending_identity_intent_required')
            intent=dict(row);self._check_intent(intent)
            actual=digest(read_regular(self.policy['profiles'][intent['profile']]))
            if actual==self.revision(intent['target_revision'])['sha256']:
                self._complete(intent);return 'complete'
            if actual==intent['old_sha256']:
                with self.db() as connection:
                    connection.execute("UPDATE intents SET status='aborted_before_replace' WHERE id=?",(identifier,))
                    self._event(connection,'application_aborted',intent['profile'],intent['target_revision'],{'intent_id':identifier})
                return 'aborted_before_replace'
            raise PermissionError('unknown_native_identity_bytes_recovery_blocked')

    def pin(self,profile,sid,role,parent_sid,build):
        active=self.active(profile)
        if not isinstance(sid,str) or not sid or len(sid)>512:raise PermissionError('identity_session_required')
        if (not parent_sid and role!='parent') or (parent_sid and role not in {'collector','analyst','reviewer','G','S','D','parser','computation'}):
            raise PermissionError('identity_role_assignment_required')
        with self.db() as connection:
            previous=connection.execute('SELECT * FROM pins WHERE profile=? AND sid=?',(profile,sid)).fetchone()
            parent=connection.execute('SELECT * FROM pins WHERE profile=? AND sid=?',(profile,parent_sid)).fetchone() if parent_sid else None
        if previous:
            return self._pin_value(dict(previous),profile,sid,role,parent_sid)
        if parent_sid and (parent is None or parent['role']!='parent' or role=='parent'):
            raise PermissionError('parent_identity_pin_required')
        if parent is not None:self._pin_value(dict(parent),profile,parent_sid,'parent','')
        revision=parent['revision'] if parent else self.active(profile)['revision']
        source=self.revision(revision)
        if source['profile']!=profile:raise PermissionError('identity_profile_lineage_mismatch')
        if source['status']=='cancelled':raise PermissionError('identity_revision_revoked')
        body=build(source,role)
        reference={'instance_id':self.policy['instance_id'],'agent_id':self.policy['agent_id'],'profile':profile,
                   'session_id':sid,'revision':revision,'source_sha256':source['sha256'],'builder':BUILDER,'role':role,
                   'parent_session_id':parent_sid,'authority_at_pin':source['status'],'body_sha256':digest(body.encode())}
        view='<BN_IDENTITY_VIEW>\n'+encoded(reference).decode()+'\n'+body+'\n</BN_IDENTITY_VIEW>'
        value=(profile,sid,revision,role,parent_sid,view,digest(view.encode()),encoded(reference).decode())
        with self.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current=connection.execute('SELECT * FROM active WHERE profile=?',(profile,)).fetchone()
            pending=connection.execute("SELECT id FROM intents WHERE profile=? AND status='prepared'",(profile,)).fetchone()
            state=connection.execute('SELECT status FROM revisions WHERE id=?',(revision,)).fetchone()[0]
            if pending is not None or state=='cancelled' or (not parent_sid and (current['revision']!=active['revision'] or current['generation']!=active['generation'])):
                raise PermissionError('identity_basis_changed_during_pin')
            connection.execute('INSERT OR IGNORE INTO pins VALUES(?,?,?,?,?,?,?,?)',value)
            self._event(connection,'session_pin',profile,revision,{'sid_sha256':digest(sid.encode()),'view_sha256':value[6]})
            actual=dict(connection.execute('SELECT * FROM pins WHERE profile=? AND sid=?',(profile,sid)).fetchone())
        return self._pin_value(actual,profile,sid,role,parent_sid)

    def _pin_value(self,value,profile,sid,role,parent_sid):
        if value['role']!=role or value['parent_sid']!=parent_sid:raise PermissionError('identity_session_binding_conflict')
        source=self.revision(value['revision']);reference=json.loads(value['reference'])
        if source['profile']!=profile:raise PermissionError('identity_profile_lineage_mismatch')
        if source['status']=='cancelled':raise PermissionError('identity_revision_revoked')
        expected={'instance_id':self.policy['instance_id'],'profile':profile,'session_id':sid,'role':role,
                  'parent_session_id':parent_sid,'revision':value['revision'],'source_sha256':source['sha256'],'builder':BUILDER}
        prefix='<BN_IDENTITY_VIEW>\n'+encoded(reference).decode()+'\n';suffix='\n</BN_IDENTITY_VIEW>'
        if any(reference.get(key)!=item for key,item in expected.items()) or not value['view'].startswith(prefix) or not value['view'].endswith(suffix):
            raise PermissionError('identity_pin_reference_mismatch')
        body=value['view'][len(prefix):-len(suffix)]
        if digest(value['view'].encode())!=value['view_sha256'] or digest(body.encode())!=reference['body_sha256']:
            raise PermissionError('identity_view_integrity_failed')
        return value

    def status(self):
        with self.db() as connection:
            counts={name:connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ['revisions','events','pins']}
            pending=[dict(row) for row in connection.execute("SELECT id,profile,status FROM intents WHERE status='prepared'")]
        profiles={}
        for name in self.policy['profiles']:
            try:profiles[name]={'state':'ready',**self.active(name)}
            except (PermissionError,OSError,ValueError) as exc:profiles[name]={'state':'blocked','reason':str(exc)}
        return {'instance_id':self.policy['instance_id'],'counts':counts,'pending':pending,
                'profiles':profiles,'deep_identity_defined':False}

    def verify(self):
        previous=None
        with self.db() as connection:
            revisions=[row[0] for row in connection.execute('SELECT id FROM revisions')]
            events=[dict(row) for row in connection.execute('SELECT * FROM events ORDER BY seq')]
        for revision in revisions:self.revision(revision)
        for event in events:
            details=json.loads(event['details'])
            expected=digest(encoded([event['kind'],event['profile'],event['revision'],details,previous,event['created']]))
            if event['previous_hash']!=previous or expected!=event['event_hash']:raise PermissionError('identity_event_chain_integrity_failed')
            if event['kind'] in {'accepted','cancelled'}:self.verify_receipt(details,'accept' if event['kind']=='accepted' else 'cancel')
            if event['kind']=='applied':self.verify_receipt(details['receipt'],details['receipt']['payload']['decision'])
            previous=expected
        return {'archive_valid':True,'revision_count':len(revisions),'event_count':len(events),**self.status()}
