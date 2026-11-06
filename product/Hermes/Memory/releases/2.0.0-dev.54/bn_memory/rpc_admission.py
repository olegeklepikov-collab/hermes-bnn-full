"""Prepared signatures are not grants. RPC needs one exact final native receipt."""
import hashlib
import hmac
import math
import re
import time
from pathlib import Path

from agent.tool_attempt import current_tool_attempt
from bn_memory.store import canonical, sha
from bn_memory.schemas import SCHEMAS

PREFIX = 'mcp__context__'
HOST_FIELDS = {'namespace', 'sid', 'expires', 'signature', 'native_nonce'}


def install(db):
    db.execute('''CREATE TABLE rpc_dispatches(profile_id TEXT NOT NULL,nonce TEXT NOT NULL,
        tool_name TEXT NOT NULL,input_hash TEXT NOT NULL,state TEXT NOT NULL,result_hash TEXT,created REAL NOT NULL,
        PRIMARY KEY(profile_id,nonce),FOREIGN KEY(profile_id,nonce) REFERENCES action_attempts(profile_id,nonce))''')
    db.execute("INSERT INTO meta VALUES('rpc_admission_contract','1')")


def verify(db):
    row = db.execute("SELECT value FROM meta WHERE key='rpc_admission_contract'").fetchone()
    if row is None or row[0] != '1': raise RuntimeError('explicit_rpc_admission_migration_required')
    db.execute('SELECT profile_id,nonce,state FROM rpc_dispatches LIMIT 0')


class RpcAdmission:
    def __init__(self, host): self.host = host

    def tools(self):
        return sorted({rule['tool'][len(PREFIX):] for rule in self.host.actions.rules.values()
                       if rule['tool'].startswith(PREFIX) and rule['tool'][len(PREFIX):] in SCHEMAS})

    def _signature(self, name, args, host):
        body = {'tool': name, 'args': args, **{key: host.get(key) for key in ['namespace','sid','expires','native_nonce']}}
        return hmac.new(Path(self.host.config['host_key']).read_bytes(), canonical(body).encode(), hashlib.sha256).hexdigest()

    def prepare(self, full_name, args, sid, *, runtime=False):
        name = full_name.removeprefix(PREFIX)
        if name not in self.tools(): raise PermissionError('rpc_tool_not_in_operator_catalog')
        attempt = current_tool_attempt()
        if attempt is not None and (not attempt.active.is_set() or attempt.tool_name != full_name or attempt.profile_home != self.host.admission.profile_home):
            raise PermissionError('rpc_native_attempt_mismatch')
        clean = {k: v for k, v in args.items() if k != '_host' and (runtime or k != '_runtime')}
        authority = {'namespace': self.host.store.namespace, 'sid': sid, 'expires': time.time() + 90,
                     'native_nonce': attempt.nonce if attempt else None}
        authority['signature'] = self._signature(name, clean, authority)
        return {**clean, '_host': authority}

    def authenticated(self, name, raw, sid=None):
        authority = raw.get('_host', {})
        if not isinstance(authority, dict) or set(authority) != HOST_FIELDS: raise PermissionError('rpc_host_contract_invalid')
        expiry = authority['expires']
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or not time.time() <= expiry <= time.time() + 120:
            raise PermissionError('rpc_signature_expired')
        if authority['namespace'] != self.host.store.namespace or not isinstance(authority['sid'], str) or sid is not None and authority['sid'] != sid:
            raise PermissionError('rpc_profile_or_session_mismatch')
        clean = {k: v for k, v in raw.items() if k != '_host'}
        signature = authority['signature']
        if not isinstance(signature, str) or not hmac.compare_digest(self._signature(name, clean, authority), signature):
            raise PermissionError('native_memory_signature_required')
        nonce = authority['native_nonce']
        if not isinstance(nonce, str) or not re.fullmatch('[0-9a-f]{32}', nonce):
            raise PermissionError('rpc_final_native_receipt_required')
        return authority

    def verify_native(self, name, raw, sid):
        authority = self.authenticated(name, raw, sid)
        attempt = current_tool_attempt()
        if attempt is None or authority['native_nonce'] != attempt.nonce: raise PermissionError('rpc_native_nonce_mismatch')

    def claim(self, name, raw):
        if name not in self.tools(): raise PermissionError('rpc_tool_not_in_operator_catalog')
        authority = self.authenticated(name, raw)
        store = self.host.store; nonce = authority['native_nonce']; sid = authority['sid']; digest = sha(canonical(raw))
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); verify(db)
            row = db.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (store.profile, nonce)).fetchone()
            if row is None or row['sid'] != sid or row['tool_name'] != PREFIX + name or row['status'] != 'admitted_outcome_unsettled' or row['input_hash'] != digest:
                raise PermissionError('rpc_exact_final_native_receipt_required')
            rule, basis = self.host.actions._permission(sid, row['turn_id'], PREFIX + name, raw)
            if basis != row['basis'] or rule['id'] != row['rule_id'] or rule['effect'] != row['effect']:
                raise PermissionError('rpc_native_authority_changed')
            if db.execute('SELECT 1 FROM rpc_dispatches WHERE profile_id=? AND nonce=?', (store.profile, nonce)).fetchone():
                raise PermissionError('rpc_attempt_already_dispatched_verify_outcome')
            db.execute('INSERT INTO rpc_dispatches VALUES(?,?,?,?,?,?,?)', (store.profile, nonce, name, digest, 'claimed_outcome_unknown', None, time.time()))
        return sid, nonce

    def finish(self, nonce, result, failed=False):
        with self.host.store.db() as db:
            db.execute('UPDATE rpc_dispatches SET state=?,result_hash=? WHERE profile_id=? AND nonce=?',
                       ('returned_error_unsettled' if failed else 'returned_unreviewed', sha(canonical(result)), self.host.store.profile, nonce))
