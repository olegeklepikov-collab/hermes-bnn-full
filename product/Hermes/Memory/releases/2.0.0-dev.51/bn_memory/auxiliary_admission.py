"""Purpose-bound, one-use auxiliary admission at the actual native boundary."""
import copy
import json
import time

from bn_memory.admission import canonical, digest, last_user
from agent.auxiliary_attempt import current_auxiliary_attempt


class AuxiliaryAdmission:
    # Other purposes remain closed until they have their own input contract.
    PURPOSES = frozenset({'compression', 'title_generation'})

    def __init__(self, host):
        self.host = host

    def native(self, identity):
        attempt = current_auxiliary_attempt()
        if attempt is None or attempt.profile_home != self.host.admission.profile_home:
            raise PermissionError('native_auxiliary_attempt_required')
        for key in ['session_id', 'turn_id', 'api_request_id', 'retry_count', 'aux_task', 'provider', 'model', 'api_mode']:
            if identity.get(key, '' if key != 'retry_count' else 0) != attempt.identity.get(key, '' if key != 'retry_count' else 0):
                raise PermissionError('auxiliary_native_identity_mismatch')
        sid = attempt.identity.get('session_id')
        purpose = attempt.identity.get('aux_task')
        if not sid or not attempt.identity.get('api_request_id') or purpose not in self.PURPOSES:
            raise PermissionError('auxiliary_owner_request_and_supported_purpose_required')
        retry = attempt.identity.get('retry_count', 0)
        if type(retry) is not int or retry < 0:
            raise PermissionError('auxiliary_attempt_number_required')
        if not attempt.identity.get('provider') or not attempt.identity.get('model'):
            raise PermissionError('auxiliary_route_required')
        return attempt, sid, purpose

    @staticmethod
    def request_hash(request):
        return digest(canonical({k: v for k, v in request.items() if k not in {'timeout', 'http_client'}}))

    def prepare(self, request, identity):
        attempt, sid, purpose = self.native(identity)
        binding = self.host.store.binding(sid)
        snapshot = self.host.admission.snapshot(sid)
        result = copy.deepcopy(request)
        receipt = canonical({'purpose': purpose, 'nonce': attempt.nonce, 'session_id': sid, 'profile_id':self.host.store.profile,
                             'role': binding['role'], 'basis': snapshot,
                             'identity_reference': self.host.identity.reference(sid) if self.host.identity else None,
                             'evidence_use': 'auxiliary_input_only_not_domain_evidence'})
        envelope = '<BN_AUXILIARY_ADMISSION>\n' + receipt + '\n</BN_AUXILIARY_ADMISSION>'
        row = last_user(result)
        if isinstance(row.get('content'), str):
            row['content'] += '\n' + envelope
        elif isinstance(row.get('content'), list):
            row['content'].append({'type': 'input_text' if 'input' in result else 'text', 'text': envelope})
        else:
            raise PermissionError('auxiliary_text_input_required')
        with self.host.store.db() as connection:
            connection.execute('INSERT INTO auxiliary_admissions VALUES(?,?,?,?,?,?,?,?,?)',
                               (attempt.nonce, sid, purpose, canonical(dict(attempt.identity)), canonical(snapshot),
                                self.request_hash(result), 'prepared', time.time(),self.host.store.profile))
        return result

    def validate(self, request, identity):
        attempt, sid, purpose = self.native(identity)
        if len(canonical({k: v for k, v in request.items() if k not in {'timeout', 'http_client'}}).encode()) > self.host.config.get('max_request_bytes', 8388608):
            raise PermissionError('native_request_size_exceeded')
        snapshot = canonical(self.host.admission.snapshot(sid))
        with self.host.store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM auxiliary_admissions WHERE profile_id=? AND nonce=?', (self.host.store.profile,attempt.nonce)).fetchone()
            if row is None or row['status'] != 'prepared':
                raise PermissionError('auxiliary_preparation_missing_or_consumed')
            if row['sid'] != sid or row['purpose'] != purpose or row['identity'] != canonical(dict(attempt.identity)):
                raise PermissionError('auxiliary_identity_mismatch')
            if row['snapshot'] != snapshot or row['request_hash'] != self.request_hash(request):
                raise PermissionError('auxiliary_basis_or_request_changed')
            connection.execute("UPDATE auxiliary_admissions SET status='admitted' WHERE profile_id=? AND nonce=?", (self.host.store.profile,attempt.nonce))
