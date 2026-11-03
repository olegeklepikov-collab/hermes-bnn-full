"""Explicit copy migration; source and prior capabilities are never silently renewed."""
from pathlib import Path
from contextlib import closing
import os
import hashlib
import sqlite3
import tempfile
from bn_memory import record_metadata
from bn_memory import namespace


def upgrade(writer, config, legacy_profile):
    schema = writer.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if not schema or schema[0] not in {'1', '2'}:
        raise ValueError('migration_source_schema_unsupported')
    for key, allowed in [('context_admission_contract', {'1','2'}),
                         ('auxiliary_checkpoint_contract', {'1'}), ('neutral_action_contract', {'1'})]:
        contract = writer.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        if contract is not None and contract[0] not in allowed:
            raise ValueError('migration_source_contract_unsupported:' + key)
    if schema[0] == '1':
        record_metadata.install(writer)
    marker = writer.execute("SELECT value FROM meta WHERE key='profile_namespace_contract'").fetchone()
    if marker is None:
        space = namespace.configuration(config or {})
        namespace.upgrade(writer, space, legacy_profile)
    else:
        if marker[0] != '1':
            raise ValueError('profile_namespace_contract_unsupported')
        if config is not None:
            namespace.verify(writer, namespace.configuration(config))
    pending = writer.execute("SELECT 1 FROM sqlite_master WHERE name='document_pending' AND type='table'").fetchone()
    if pending and 'profile_id' not in {row[1] for row in writer.execute('PRAGMA table_info(document_pending)')}:
        space = namespace.configuration(config or {})
        if legacy_profile != space['profile_id']:
            raise PermissionError('explicit_legacy_document_origin_required')
        writer.execute('ALTER TABLE document_pending ADD COLUMN profile_id TEXT')
        writer.execute('UPDATE document_pending SET profile_id=?', (legacy_profile,))
        writer.execute("UPDATE document_pending SET state='failed' WHERE state IN ('pending','scheduled')")
    for key, value in [('schema','2'), ('context_admission_contract','2'),
                       ('auxiliary_checkpoint_contract','1'), ('neutral_action_contract','1')]:
        writer.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,value))
    writer.execute("UPDATE context_admissions SET status='failed'")
    writer.execute("UPDATE launch_grants SET state='cancelled' WHERE state IN ('prepared','admitted')")
    writer.execute("UPDATE sessions SET role='unassigned',assignment_id='',purpose='' WHERE readonly=1")
    writer.execute("UPDATE auxiliary_admissions SET status='abandoned' WHERE status='prepared'")
    working=writer.execute("SELECT value FROM meta WHERE key='working_contract'").fetchone()
    if working is None:
        from bn_memory.working import install as install_working
        install_working(writer)
    elif working[0]!='1':raise ValueError('working_contract_unsupported')
    retry=writer.execute("SELECT value FROM meta WHERE key='action_retry_contract'").fetchone()
    if retry is None:
        from bn_memory.action_retry import install as install_retry
        install_retry(writer)
    elif retry[0]!='1':raise ValueError('action_retry_contract_unsupported')
    reviews=writer.execute("SELECT value FROM meta WHERE key='action_review_contract'").fetchone()
    from bn_memory.action_review import install as install_reviews, retire_permits
    if reviews is None:install_reviews(writer)
    elif reviews[0]!='1':raise ValueError('action_review_contract_unsupported')
    retire_permits(writer)
    rpc=writer.execute("SELECT value FROM meta WHERE key='rpc_admission_contract'").fetchone()
    if rpc is None:
        from bn_memory.rpc_admission import install as install_rpc
        install_rpc(writer)
    elif rpc[0]!='1':raise ValueError('rpc_admission_contract_unsupported')
    source_policy=writer.execute("SELECT value FROM meta WHERE key='source_visibility_contract'").fetchone()
    if source_policy is None:
        from bn_memory.source_visibility import install as install_visibility
        install_visibility(writer)
    elif source_policy[0]!='1':raise ValueError('source_visibility_contract_unsupported')
    compute=writer.execute("SELECT value FROM meta WHERE key='isolated_compute_contract'").fetchone()
    if compute is None:
        from bn_memory.compute import install as install_compute
        install_compute(writer)
    elif compute[0]!='1':raise ValueError('isolated_compute_contract_unsupported')
    for marker,version,module in [('memory_envelope_contract','2','bn_memory.envelope'),('context_packet_contract','2','bn_memory.packet')]:
        old=writer.execute('SELECT value FROM meta WHERE key=?',(marker,)).fetchone()
        if old is None:
            install=__import__(module,fromlist=['install']).install
            if module=='bn_memory.envelope':install(writer,namespace.configuration(config)['owner_id'])
            else:install(writer)
        elif old[0]!=version:raise ValueError('migration_source_contract_unsupported:'+marker)
    marker=writer.execute("SELECT value FROM meta WHERE key='source_fts_contract'").fetchone()
    if marker is None:
        from bn_memory.source_fts import install as install_source_fts
        install_source_fts(writer)
    elif marker[0]!='1':raise ValueError('source_fts_contract_unsupported')
    marker=writer.execute("SELECT value FROM meta WHERE key='embedding_contract'").fetchone()
    if marker is None:
        from bn_memory.embedding_contract import install as install_embeddings
        install_embeddings(writer)
    elif marker[0]!='2':raise ValueError('embedding_contract_unsupported')
    writer.execute('UPDATE sessions SET context=NULL,turn=NULL')
    # action_attempts and checkpoint payloads retain their exact outcome/history.


def migrate(source, destination, config=None, *, legacy_profile=None):
    source, destination = Path(source).resolve(strict=True), Path(destination).absolute()
    if source == destination.resolve() or destination.exists():
        raise FileExistsError('migration_requires_new_destination')
    with source.open('rb') as handle:
        source_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.memory-v2-', dir=destination.parent)
    os.close(fd)
    staging = Path(temporary)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader:
            before = reader.execute('PRAGMA data_version').fetchone()[0]
            with closing(sqlite3.connect(staging)) as writer:
                reader.backup(writer)
                writer.execute('PRAGMA journal_mode=DELETE')
                writer.execute('PRAGMA foreign_keys=OFF')
                writer.execute('BEGIN IMMEDIATE')
                upgrade(writer, config, legacy_profile)
                if writer.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('migrated_database_foreign_key_failure')
                writer.commit()
                if writer.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('migrated_database_integrity_failed')
                records = writer.execute('SELECT COUNT(*) FROM records').fetchone()[0]
            if reader.execute('PRAGMA data_version').fetchone()[0] != before:
                raise RuntimeError('migration_source_changed')
        with source.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != source_hash:
                raise RuntimeError('migration_source_changed')
        os.link(staging, destination)
        destination.chmod(0o600)
        return {'schema': 2, 'namespace_contract': 1, 'records': records, 'source_unchanged': True,
                'legacy_origin_profile': legacy_profile, 'source_sha256': source_hash,
                'destination': str(destination), 'previous_capabilities_restored': False}
    finally:
        staging.unlink(missing_ok=True)
