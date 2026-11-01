"""Authenticated transaction intent beside the unchanged supplier SQLite store."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import time

from .codec import canonical


def atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.anchor-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def _key(settings):
    return Path(settings['native_key']).read_bytes()


def _sealed(settings, body):
    return canonical({'body': body, 'mac': hmac.new(_key(settings), canonical(body), hashlib.sha256).hexdigest()})


def _read(settings, path):
    if path.is_symlink():
        raise ValueError('DEGRADED: unsafe independent anchor path')
    envelope = json.loads(path.read_bytes())
    body = envelope['body']
    expected = hmac.new(_key(settings), canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(envelope['mac'], expected):
        raise ValueError('DEGRADED: independent anchor authentication failed')
    if body['engine_manifest_sha256'] != settings['engine_manifest_sha256']:
        raise ValueError('DEGRADED: independent anchor engine changed')
    return body


def _db(settings):
    return Path(settings['state_dir']) / 'state.sqlite3'


def _intent(settings):
    return Path(settings['anchor_file']).with_name('anchor-intent.json')


def logical_root(connection):
    """Cover every persistent schema object and both complete signed record sets."""
    digest = hashlib.sha256()
    schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    digest.update(canonical(schema))
    for identifier, revision, raw, mac in connection.execute('SELECT id,revision,payload,mac FROM records ORDER BY id'):
        digest.update(canonical(['record', identifier, revision, hashlib.sha256(raw).hexdigest(), mac]))
    for scope, request, fingerprint, raw, mac in connection.execute('SELECT scope,request_id,fingerprint,payload,mac FROM requests ORDER BY scope,request_id'):
        digest.update(canonical(['request', scope, request, fingerprint, hashlib.sha256(raw).hexdigest(), mac]))
    return digest.hexdigest()


def _root(settings):
    with sqlite3.connect('file:' + str(_db(settings)) + '?mode=ro', uri=True) as connection:
        return logical_root(connection)


def anchor(settings):
    body = {'version': 2, 'database_sha256': hashlib.sha256(_db(settings).read_bytes()).hexdigest(),
            'logical_sha256': _root(settings), 'recorded_at': time.time(),
            'engine_manifest_sha256': settings['engine_manifest_sha256']}
    atomic(Path(settings['anchor_file']), _sealed(settings, body))
    _intent(settings).unlink(missing_ok=True)
    return body


def check_anchor(settings, initializing=False):
    db, path, intent_path = _db(settings), Path(settings['anchor_file']), _intent(settings)
    if initializing and not db.exists() and not path.exists() and not intent_path.exists():
        return
    if not db.is_file() or db.is_symlink() or not path.is_file():
        raise ValueError('DEGRADED: missing independent recovery anchor')
    previous = _read(settings, path)
    physical = hashlib.sha256(db.read_bytes()).hexdigest()
    if intent_path.exists():
        intent = _read(settings, intent_path)
        if physical == previous['database_sha256'] and previous.get('logical_sha256') == intent['after_logical_sha256']:
            intent_path.unlink()
            return previous
        if intent['previous_anchor_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('DEGRADED: recovery intent belongs to another anchor')
        current = _root(settings)
        if intent['before_logical_sha256'] != previous.get('logical_sha256'):
            raise ValueError('DEGRADED: recovery intent predecessor differs')
        if current not in {intent['before_logical_sha256'], intent['after_logical_sha256']}:
            raise ValueError('DEGRADED: interrupted transaction has no authenticated outcome')
        return anchor(settings)
    if physical == previous['database_sha256']:
        return previous
    if previous.get('version') == 2 and _root(settings) == previous['logical_sha256']:
        return anchor(settings)
    raise ValueError('DEGRADED: database does not match its independent anchor')


def install_store_guard(settings):
    """Record the prospective authenticated root before the supplier commits."""
    from gsd_bridge.store import Store
    if getattr(Store.transaction, '_bn_anchor_guard', False):
        if Store.transaction._bn_anchor_settings != str(_db(settings).resolve()):
            raise ValueError('A store guard is already bound to another profile')
        return
    original = Store.transaction

    @contextmanager
    def transaction(store):
        db = _db(settings)
        if store.db_path.resolve() != db.resolve():
            raise ValueError('The transaction belongs to another GSD store')
        if shutil.disk_usage(db.parent).free < max(128 * 1024 * 1024, db.stat().st_size * 3):
            raise OSError('Insufficient free storage for an anchored GSD transaction')
        path = Path(settings['anchor_file'])
        # Upgrade a matching legacy seal before the first guarded transaction.
        if not path.exists() or _read(settings, path).get('version') != 2:
            anchor(settings)
        with original(store) as connection:
            before = logical_root(connection)
            if before != _read(settings, path)['logical_sha256']:
                raise ValueError('DEGRADED: transaction predecessor differs from its anchor')
            yield connection
            after = logical_root(connection)
            if after != before:
                body = {'version': 1, 'previous_anchor_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'before_logical_sha256': before, 'after_logical_sha256': after,
                        'engine_manifest_sha256': settings['engine_manifest_sha256'], 'recorded_at': time.time()}
                atomic(_intent(settings), _sealed(settings, body))
        if _intent(settings).exists():
            anchor(settings)

    transaction._bn_anchor_guard = True
    transaction._bn_anchor_settings = str(_db(settings).resolve())
    Store.transaction = transaction


def recover_legacy_by_operator(settings, *, expected_database_sha256, expected_anchor_sha256, reason):
    """Offline operator reconciliation; deliberately absent from model/RPC methods."""
    path = Path(settings['anchor_file'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_anchor_sha256:
        raise ValueError('The operator-reviewed anchor changed')
    previous = _read(settings, path)
    if previous['version'] != 1 or not reason.strip():
        raise ValueError('Explicit legacy recovery reason required')
    db = _db(settings)
    if hashlib.sha256(db.read_bytes()).hexdigest() != expected_database_sha256:
        raise ValueError('The operator-reviewed database changed')
    key = Path(settings['store_key']).read_bytes()
    counts = {}
    with sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity failure')
        objects = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        if objects != [('records',), ('requests',)]:
            raise ValueError('Unexpected supplier state schema')
        extras = connection.execute("SELECT name FROM sqlite_master WHERE type NOT IN ('table','index') OR (type='index' AND name NOT IN ('sqlite_autoindex_records_1','sqlite_autoindex_requests_1'))").fetchall()
        if extras:
            raise ValueError('Unexpected supplier state schema objects')
        for table, sql in [('records', 'SELECT id,revision,payload,mac FROM records'),
                           ('requests', 'SELECT scope,request_id,fingerprint,payload,mac FROM requests')]:
            counts[table] = 0
            for row in connection.execute(sql):
                context = ['record', *row[:-2]] if table == 'records' else ['request', *row[:-2]]
                raw, mac = row[-2:]
                expected = hmac.new(key, canonical(context) + b'\x00' + raw, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(mac, expected):
                    raise ValueError('Signed supplier row authentication failed')
                json.loads(raw)
                counts[table] += 1
    recovered = anchor(settings)
    receipt = {'operation': 'explicit_operator_legacy_reconciliation', 'reason': reason,
               'previous_anchor': previous, 'reviewed_database_sha256': expected_database_sha256,
               'signed_rows_verified': counts, 'new_anchor': recovered,
               'data_rows_modified': False, 'exact_previous_database_image_reconstructed': False}
    atomic(path.with_name('anchor-operator-recovery-' + str(time.time_ns()) + '.json'), _sealed(settings, receipt | {'engine_manifest_sha256': settings['engine_manifest_sha256']}))
    return receipt
