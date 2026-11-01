"""Operator-only entry: private signing key never loaded by the runtime adapter."""
import uuid
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .io import encoded,read_regular,save_new,digest,sync_directory


def sign_receipt(store,*,decision,revision,reviewed_sha256,reason,expected_revision=None,expected_sha256=None):
    if decision not in {'accept','apply','rollback','cancel'} or not reason.strip():raise ValueError('explicit_owner_decision_and_reason_required')
    row=store.revision(revision)
    if reviewed_sha256!=row['sha256']:raise ValueError('reviewed_identity_hash_mismatch')
    if decision in {'apply','rollback'} and (not expected_revision or not expected_sha256):
        raise ValueError('expected_native_revision_and_hash_required')
    payload={'instance_id':store.policy['instance_id'],'profile':row['profile'],'decision':decision,'revision':revision,
             'manifest_sha256':row['manifest_sha256'],'source_sha256':row['sha256'],'expected_status':row['status'],
             'expected_revision':expected_revision,'expected_sha256':expected_sha256,'reason':reason,'nonce':uuid.uuid4().hex}
    private=Ed25519PrivateKey.from_private_bytes(read_regular(store.root/'owner.key'))
    return {'payload':payload,'signature':private.sign(encoded(payload)).hex()}


def export_template(source,destination):
    raw=read_regular(source)
    if not raw.decode('utf-8').strip():raise ValueError('explicit_nonempty_curated_template_required')
    destination=Path(destination).resolve();destination.mkdir(mode=0o700)
    save_new(destination/'SOUL.md',raw)
    value={'schema':1,'instance_id':str(uuid.uuid4()),'source':'explicit_operator_selected_template',
           'sha256':digest(raw),'private_history_included':False,'authority_included':False}
    save_new(destination/'template.json',encoded(value));sync_directory(destination)
    return value
