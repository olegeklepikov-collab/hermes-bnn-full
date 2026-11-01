"""Operator-attested action outcomes and single-use permits, never model authority.

The operator entry point is a trusted process boundary, not human authentication or
OS isolation. Unrestricted same-user model execution must remain unavailable.
"""
import hashlib
import os
import stat
import time
import uuid
from pathlib import Path

import psutil
from bn_memory.store import canonical, sha, SENSITIVE, PRIVATE
from bn_memory.action_retry import EFFECTS, UNKNOWN


def install(db):
    definitions = [
        '''CREATE TABLE action_execution(profile_id TEXT NOT NULL,nonce TEXT NOT NULL,
           pid INTEGER NOT NULL,process_created REAL NOT NULL,ended REAL,
           PRIMARY KEY(profile_id,nonce),FOREIGN KEY(profile_id,nonce) REFERENCES action_attempts(profile_id,nonce))''',
        '''CREATE TABLE action_reviews(profile_id TEXT NOT NULL,nonce TEXT NOT NULL,revision INTEGER NOT NULL,
           body TEXT NOT NULL,sha256 TEXT NOT NULL,evidence BLOB NOT NULL,
           PRIMARY KEY(profile_id,nonce,revision),FOREIGN KEY(profile_id,nonce) REFERENCES action_attempts(profile_id,nonce))''',
        '''CREATE TABLE action_permits(profile_id TEXT NOT NULL,id TEXT NOT NULL,nonce TEXT NOT NULL,
           review_revision INTEGER NOT NULL,target_sid TEXT NOT NULL,target_authority TEXT NOT NULL,
           PRIMARY KEY(profile_id,id),UNIQUE(profile_id,nonce,review_revision),
           FOREIGN KEY(profile_id,nonce,review_revision) REFERENCES action_reviews(profile_id,nonce,revision),
           FOREIGN KEY(profile_id,target_sid) REFERENCES sessions(profile_id,sid))''',
        '''CREATE TABLE action_permit_events(profile_id TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,
           state TEXT NOT NULL,by_nonce TEXT,created REAL NOT NULL,PRIMARY KEY(profile_id,id,revision),
           FOREIGN KEY(profile_id,id) REFERENCES action_permits(profile_id,id),
           FOREIGN KEY(profile_id,by_nonce) REFERENCES action_attempts(profile_id,nonce))''',
    ]
    for statement in definitions: db.execute(statement)
    db.execute("INSERT INTO meta VALUES('action_review_contract','1')")


def verify(db):
    marker = db.execute("SELECT value FROM meta WHERE key='action_review_contract'").fetchone()
    if marker is None or marker[0] != '1': raise RuntimeError('explicit_action_review_migration_required')
    for table in ['action_execution', 'action_reviews', 'action_permits', 'action_permit_events']:
        db.execute('SELECT profile_id FROM ' + table + ' LIMIT 0')


def start_native(db, profile, nonce):
    verify(db)
    process = psutil.Process(os.getpid())
    db.execute('INSERT OR IGNORE INTO action_execution VALUES(?,?,?,?,NULL)',
               (profile, nonce, process.pid, process.create_time()))


def end_native(store, attempt):
    if attempt is None or attempt.profile_home != str(Path(store.config['profile_home']).resolve()): return
    with store.db() as db:
        row = db.execute('SELECT effect,input_hash,status FROM action_attempts WHERE profile_id=? AND nonce=?', (store.profile, attempt.nonce)).fetchone()
        if row is None or row['effect'] not in EFFECTS or row['input_hash'] is None: return
        verify(db)
        db.execute('UPDATE action_execution SET ended=? WHERE profile_id=? AND nonce=? AND ended IS NULL',
                   (time.time(), store.profile, attempt.nonce))
        if row['status'] == 'returned_pending_native_end':
            db.execute("UPDATE action_attempts SET status='returned_unreviewed' WHERE profile_id=? AND nonce=?", (store.profile, attempt.nonce))


def native_stopped(db, profile, nonce):
    execution = db.execute('SELECT * FROM action_execution WHERE profile_id=? AND nonce=?', (profile, nonce)).fetchone()
    if execution is None: return False
    if execution['ended'] is not None: return True
    try:
        process = psutil.Process(execution['pid'])
        return process.create_time() != execution['process_created'] or not process.is_running()
    except psutil.NoSuchProcess: return True
    except (psutil.AccessDenied, OSError): return False


def evidence_bytes(path, expected):
    path = Path(path).absolute()
    if any(part in PRIVATE for part in path.parts): raise PermissionError('private_authority_is_not_review_evidence')
    if any(parent.is_symlink() for parent in [path, *path.parents]): raise PermissionError('review_evidence_symlink_forbidden')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode): raise ValueError('regular_review_evidence_required')
        if not 0 < before.st_size <= 1048576: raise ValueError('review_evidence_receipt_limit_1MiB_do_not_trim')
        data = stream.read(1048577); after = os.fstat(stream.fileno())
        fields = ['st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns']
        if any(getattr(before, name) != getattr(after, name) for name in fields) or len(data) != before.st_size:
            raise PermissionError('review_evidence_changed_during_capture')
    if hashlib.sha256(data).hexdigest() != expected: raise PermissionError('review_evidence_sha256_mismatch')
    if SENSITIVE.search(data.decode('utf-8', errors='ignore')): raise PermissionError('secret_in_review_evidence')
    return data


def latest_review(db, profile, nonce):
    import json
    row = db.execute('SELECT * FROM action_reviews WHERE profile_id=? AND nonce=? ORDER BY revision DESC LIMIT 1', (profile, nonce)).fetchone()
    if row is None: return None
    if sha(row['body']) != row['sha256']: raise PermissionError('action_review_integrity_failed')
    body = json.loads(row['body'])
    if hashlib.sha256(row['evidence']).hexdigest() != body['evidence']['sha256']:
        raise PermissionError('action_review_evidence_integrity_failed')
    return body


def permit_state(db, profile, identifier):
    row = db.execute('SELECT * FROM action_permit_events WHERE profile_id=? AND id=? ORDER BY revision DESC LIMIT 1', (profile, identifier)).fetchone()
    if row is None: raise PermissionError('action_permit_state_missing')
    return dict(row)


def event(db, profile, identifier, state, by_nonce=None):
    revision = db.execute('SELECT coalesce(max(revision),0)+1 FROM action_permit_events WHERE profile_id=? AND id=?', (profile, identifier)).fetchone()[0]
    db.execute('INSERT INTO action_permit_events VALUES(?,?,?,?,?,?)', (profile, identifier, revision, state, by_nonce, time.time()))


def retire_permits(db):
    rows = db.execute('SELECT profile_id,id FROM action_permits').fetchall()
    for profile, identifier in rows:
        state = db.execute('SELECT state FROM action_permit_events WHERE profile_id=? AND id=? ORDER BY revision DESC LIMIT 1', (profile, identifier)).fetchone()
        if state is None: raise PermissionError('action_permit_state_missing')
        if state[0] == 'active': event(db, profile, identifier, 'retired_on_migration')


def consume(db, profile, previous, new_nonce):
    """Caller holds the same transaction as final native admission."""
    verify(db)
    review = latest_review(db, profile, previous['nonce'])
    if review is None or review['outcome'] != 'not_performed': return False
    if review['arguments_sha256'] != previous['arguments_sha256']: raise PermissionError('action_review_fingerprint_changed')
    raw = db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (profile, previous['nonce'])).fetchone()
    if sha(canonical(dict(raw))) != review['attempt_sha256']: raise PermissionError('action_review_attempt_changed')
    permit = db.execute('SELECT * FROM action_permits WHERE profile_id=? AND nonce=? AND review_revision=?', (profile, previous['nonce'], review['revision'])).fetchone()
    if permit is None: return False
    state = permit_state(db, profile, permit['id'])
    if state['state'] == 'consumed':
        if state['by_nonce'] == new_nonce: return True  # Nested boundary of the same physical attempt.
        child = db.execute('''SELECT a.status,f.arguments_sha256 FROM action_attempts a
            JOIN action_fingerprints f ON f.profile_id=a.profile_id AND f.nonce=a.nonce
            WHERE a.profile_id=? AND a.nonce=?''', (profile, state['by_nonce'])).fetchone()
        # No recursion: a failed retry remains a separate blocker in the caller's complete query.
        return child is not None and child['status'] in UNKNOWN and child['arguments_sha256'] == previous['arguments_sha256']
    current = db.execute('SELECT sid,basis FROM action_attempts WHERE profile_id=? AND nonce=?', (profile, new_nonce)).fetchone()
    if state['state'] != 'active' or current is None or permit['target_sid'] != current['sid']: return False
    import json
    if canonical(json.loads(current['basis'])[0]) != permit['target_authority']:
        raise PermissionError('retry_target_authority_changed')
    if not native_stopped(db, profile, previous['nonce']): raise PermissionError('prior_native_executor_not_stopped')
    event(db, profile, permit['id'], 'consumed', new_nonce)
    return True


class Reviews:
    def __init__(self, store): self.store = store; self.profile = store.profile

    def inspect(self, nonce):
        with self.store.db() as db:
            verify(db)
            row = db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            if row is None: raise PermissionError('action_not_in_this_profile')
            fingerprint = db.execute('SELECT arguments_sha256 FROM action_fingerprints WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            review = latest_review(db, self.profile, nonce)
            return {'attempt': dict(row), 'attempt_sha256': sha(canonical(dict(row))),
                    'arguments_sha256': fingerprint[0] if fingerprint else None,
                    'native_executor_stopped': native_stopped(db, self.profile, nonce), 'review': review,
                    'operator_statement_is_not_automatic_proof': True}

    def _dedup(self, db, operation, request_id, payload):
        import json
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 200: raise ValueError('operator_request_id_required')
        key = 'action-operator:' + sha(canonical([self.store.namespace, operation, request_id]))
        digest = sha(canonical(payload))
        row = db.execute('SELECT input_hash,result FROM operations WHERE key=?', (key,)).fetchone()
        if row and row['input_hash'] != digest: raise ValueError('operator_request_id_conflict')
        return key, digest, json.loads(row['result']) if row else None

    def review(self, *, nonce, expected_attempt_sha256, expected_revision, outcome, operator, reason,
               evidence_file, evidence_sha256, external_quiescent, request_id):
        if outcome not in {'performed', 'not_performed', 'unknown'} or type(external_quiescent) is not bool:
            raise ValueError('operator_outcome_contract_invalid')
        if type(expected_revision) is not int or expected_revision < 0: raise ValueError('review_revision_required')
        for text in [operator, reason]:
            if not isinstance(text, str) or not text.strip() or len(text) > 2048 or SENSITIVE.search(text): raise ValueError('operator_and_nonsecret_reason_required')
        evidence = evidence_bytes(evidence_file, evidence_sha256)
        payload = dict(nonce=nonce, expected_attempt_sha256=expected_attempt_sha256, expected_revision=expected_revision,
                       outcome=outcome, operator=operator, reason=reason, external_quiescent=external_quiescent,
                       evidence={'sha256': evidence_sha256, 'bytes': len(evidence), 'source_path': str(Path(evidence_file).absolute())})
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE'); verify(db)
            key, digest, duplicate = self._dedup(db, 'review', request_id, payload)
            if duplicate: return {**duplicate, 'duplicate': True}
            row = db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            if row is None or row['effect'] not in EFFECTS or row['status'] not in UNKNOWN: raise PermissionError('unknown_effectful_action_required')
            if sha(canonical(dict(row))) != expected_attempt_sha256: raise ValueError('action_review_attempt_changed')
            prior = latest_review(db, self.profile, nonce)
            if (prior['revision'] if prior else 0) != expected_revision: raise ValueError('action_review_revision_conflict')
            if outcome != 'unknown' and (not external_quiescent or not native_stopped(db, self.profile, nonce)):
                raise PermissionError('definitive_review_requires_native_stop_and_external_quiescence')
            body = {**payload, 'contract': 'BNActionReviewV1', 'revision': expected_revision + 1,
                    'attempt_sha256': expected_attempt_sha256,
                    'profile_id': self.profile, 'owner_id': self.store.namespace['owner_id'],
                    'conclusion_status': 'operator_attested', 'created': time.time()}
            fingerprint = db.execute('SELECT arguments_sha256 FROM action_fingerprints WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            body['arguments_sha256'] = fingerprint[0] if fingerprint else None
            text = canonical(body)
            db.execute('INSERT INTO action_reviews VALUES(?,?,?,?,?,?)', (self.profile, nonce, body['revision'], text, sha(text), evidence))
            result = {'nonce': nonce, 'revision': body['revision'], 'outcome': outcome, 'retry_permission': False,
                      'evidence_sha256': evidence_sha256, 'conclusion_status': 'operator_attested'}
            db.execute('INSERT INTO operations VALUES(?,?,?)', (key, digest, canonical(result)))
        return result

    def permit(self, *, nonce, review_revision, target_sid, request_id):
        if type(review_revision) is not int or review_revision < 1: raise ValueError('positive_review_revision_required')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE'); verify(db)
            payload = {'nonce': nonce, 'review_revision': review_revision, 'target_sid': target_sid}
            key, digest, duplicate = self._dedup(db, 'permit', request_id, payload)
            if duplicate:
                return {**duplicate, 'state': permit_state(db, self.profile, duplicate['permit_id'])['state'], 'duplicate': True}
            row = db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            review = latest_review(db, self.profile, nonce)
            if row is None or review is None or review['revision'] != review_revision or review['outcome'] != 'not_performed': raise PermissionError('current_not_performed_review_required')
            if sha(canonical(dict(row))) != review['attempt_sha256']: raise PermissionError('action_review_attempt_changed')
            if not native_stopped(db, self.profile, nonce): raise PermissionError('prior_native_executor_not_stopped')
            fingerprint = db.execute('SELECT arguments_sha256 FROM action_fingerprints WHERE profile_id=? AND nonce=?', (self.profile, nonce)).fetchone()
            if fingerprint is None: raise PermissionError('legacy_arguments_cannot_be_invented')
            if fingerprint[0] != review['arguments_sha256']: raise PermissionError('action_review_fingerprint_changed')
            session = db.execute('SELECT readonly FROM sessions WHERE profile_id=? AND sid=?', (self.profile, target_sid)).fetchone()
            if session is None or session['readonly']: raise PermissionError('explicit_native_parent_target_required')
            authority = db.execute("SELECT binding_hash,profile_hash,policy_revision FROM context_admissions WHERE profile_id=? AND sid=? AND status='ready'", (self.profile, target_sid)).fetchone()
            if authority is None: raise PermissionError('current_native_target_admission_required')
            if db.execute('SELECT 1 FROM action_permits WHERE profile_id=? AND nonce=? AND review_revision=?', (self.profile, nonce, review_revision)).fetchone(): raise PermissionError('one_permit_per_review_new_review_required')
            identifier = 'RETRY-' + uuid.uuid4().hex
            db.execute('INSERT INTO action_permits VALUES(?,?,?,?,?,?)', (self.profile, identifier, nonce, review_revision, target_sid, canonical(tuple(authority))))
            event(db, self.profile, identifier, 'active')
            result = {'permit_id': identifier, **payload, 'state': 'active', 'single_use': True, 'action_executed': False}
            db.execute('INSERT INTO operations VALUES(?,?,?)', (key, digest, canonical(result)))
        return result

    def revoke(self, identifier):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE'); verify(db)
            state = permit_state(db, self.profile, identifier)['state']
            if state == 'consumed': raise PermissionError('consumed_permit_cannot_be_reversed')
            if state == 'active': event(db, self.profile, identifier, 'revoked')
        return {'permit_id': identifier, 'state': 'revoked' if state == 'active' else state, 'action_executed': False}
