"""Canonical passports over the primary ledger; provenance is never model authority."""
import json
import time
from bn_memory.record_metadata import canonical
from hashlib import sha256

CONTRACT = 'MemoryEnvelopeV2'


def install(db, owner_id):
    db.execute('CREATE TABLE memory_envelopes(id TEXT, revision INTEGER, payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(id,revision), FOREIGN KEY(id,revision) REFERENCES records(id,revision))')
    db.execute('CREATE TABLE memory_events(seq INTEGER PRIMARY KEY, id TEXT NOT NULL, revision INTEGER NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(id,revision), FOREIGN KEY(id,revision) REFERENCES records(id,revision))')
    db.execute("INSERT INTO meta VALUES('memory_envelope_contract','2')")
    cursor=db.execute('SELECT * FROM records ORDER BY id,revision')
    names=[column[0] for column in cursor.description]
    for row in cursor.fetchall():
        write(db, dict(zip(names,row)), owner_id, None, None, 'legacy_import')


def write(db, row, owner_id, binding, metadata, event):
    if metadata is None:
        from bn_memory.record_metadata import read
        metadata = read(db, row['id'], row['revision'])
    prior = db.execute('SELECT revision FROM records WHERE id=? AND revision<? ORDER BY revision DESC LIMIT 1', (row['id'], row['revision'])).fetchone()
    oldref = {'id': row['id'], 'revision': prior[0]} if prior else None
    from bn_memory.write_origin import for_binding
    origin=for_binding(binding) if binding else {'step_id':None,'attempt_id':None}
    envelope = {
        'contract': CONTRACT, 'version': 2, 'id': row['id'], 'revision': row['revision'],
        'content_hash': row['content_hash'], 'content_ref': {'primary':'sqlite', 'id':row['id'], 'revision':row['revision']},
        'owner_id': owner_id, 'profile_id': binding['profile_id'] if binding else None,
        'project_id': binding['project'] if binding else None, 'task_id': binding['task'] if binding else None,
        'session_id': binding['sid'] if binding else None, **{k:origin[k] for k in ['step_id','attempt_id']},
        'parent_refs': metadata.get('source_dependencies', []), 'supersedes': oldref,
        'source_refs': [{'reference':row['source'], 'verification':'not_verified_by_registration'}],
        'authority_class':'memory_data', 'evidence_status':'unreviewed', 'review_status':'not_reviewed',
        'visibility':metadata['visibility'], 'permitted_purposes':['retrieval_as_data'],
        'observed_at':None, 'ingested_at':row['created'], 'event_time':metadata.get('event_time'),
        'valid_from':metadata.get('valid_from'), 'valid_to':metadata.get('valid_to'),
        'status':row['status'], 'stale_reason':None,
        'retracted_by': {'id':row['id'], 'revision':row['revision']} if row['status']=='retracted' else None,
        'horizon':metadata['horizon'], 'memory_type':metadata['memory_type'], 'legacy_kind':row['kind'],
        'applicability':{'scope':row['scope'], 'limits':'Source claims are data; no scientific or operator acceptance implied.'},
        'provenance':{'event':event, 'origin':'native_session' if binding else 'legacy_unknown',
                      'unknown_fields_explicit':True}}
    raw=canonical(envelope)
    db.execute('INSERT INTO memory_envelopes VALUES(?,?,?,?)',(row['id'],row['revision'],raw,sha256(raw.encode()).hexdigest()))
    db.execute('INSERT INTO memory_events(id,revision,event,payload) VALUES(?,?,?,?)',
               (row['id'],row['revision'],event,canonical({'envelope_sha256':sha256(raw.encode()).hexdigest(),'committed_at':time.time()})))
    # Older deliveries remain historical receipts, never current projections.
    if event!='legacy_import':
        db.execute("UPDATE outbox SET status='superseded' WHERE id=? AND revision<?",(row['id'],row['revision']))
    return envelope


def read(db, identifier, revision):
    row=db.execute('SELECT payload,sha256 FROM memory_envelopes WHERE id=? AND revision=?',(identifier,revision)).fetchone()
    if row is None or sha256(row[0].encode()).hexdigest()!=row[1]:
        raise RuntimeError('memory_envelope_integrity_failed')
    result=json.loads(row[0])
    if result.get('contract')!=CONTRACT or result.get('authority_class')!='memory_data' or result.get('review_status')!='not_reviewed':
        raise RuntimeError('memory_envelope_authority_invalid')
    return result


def projections(db, identifier,expected_space=None,expected_targets=None):
    current=db.execute('SELECT revision FROM current WHERE id=?',(identifier,)).fetchone()
    if not current:raise ValueError('record_not_found')
    answer=[]
    for backend in ['agentmemory','graphiti','zvec']:
        row=db.execute('SELECT status,receipt FROM outbox WHERE id=? AND revision=? AND backend=?',(identifier,current[0],backend)).fetchone()
        applied=db.execute("SELECT MAX(revision) FROM outbox WHERE id=? AND backend=? AND receipt IS NOT NULL AND json_extract(receipt,'$.status') IN ('indexed','deleted') AND status IN ('indexed','superseded')",(identifier,backend)).fetchone()[0]
        item={'backend':backend,'expected_revision':current[0], 'applied_revision':applied,
              'status':row[0] if row else 'missing','current':bool(row and row[0]=='indexed'),
              'outcome':json.loads(row[1]).get('status','unknown') if row and row[1] else 'not_attempted'}
        if backend=='zvec' and expected_space:
            actual=json.loads(row[1]).get('space_id') if row and row[1] else None
            item.update(expected_space=expected_space,applied_space=actual)
            if actual!=expected_space:
                item['current']=False
                if row and row[0]=='indexed':item['status']='needs_space_rebuild'
        if expected_targets and backend in expected_targets:
            actual=json.loads(row[1]).get('projection_target') if row and row[1] else None
            item.update(expected_target=expected_targets[backend],applied_target=actual)
            if actual!=expected_targets[backend]:
                item['current']=False
                if row and row[0]=='indexed':item['status']='needs_target_rebind'
        answer.append(item)
    return answer
