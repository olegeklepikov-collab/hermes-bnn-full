"""Lossless, session-bound pages for large retrieval results; never filesystem grants."""
import json,re,time,uuid
from bn_memory.store import canonical,sha


def retain(broker,sid,result,basis):
    raw=canonical(result)
    if len(raw)<=8000:return result
    if broker.store.retrieval_basis(sid)!=basis:raise PermissionError('recall_basis_changed_refresh_required')
    identifier='RCL-'+uuid.uuid4().hex
    with broker.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS recall_results(profile_id TEXT,sid TEXT,id TEXT,basis TEXT,sha256 TEXT,body TEXT,created REAL,PRIMARY KEY(profile_id,id))')
        db.execute('INSERT INTO recall_results VALUES(?,?,?,?,?,?,?)',(broker.store.profile,sid,identifier,basis,sha(raw),raw,time.time()))
    refs=lambda values:[{k:v[k] for k in ['id','revision','content_hash'] if k in v} for v in values]
    records=refs(result.get('records',[]));sources=refs(result.get('source_fragments',[]))
    chosen={v['id'] for v in records+sources}
    backends={}
    for name,value in result.get('derived',{}).items():
        backends[name]={'status':value.get('status'),'match_count':len(value.get('matches',[])),
            'returned_ids':[v['id'] for v in value.get('matches',[]) if v.get('id') in chosen],
            **({'code':value['code']} if 'code' in value else {})}
    return {'contract':'BNNRecallReferenceV1','result_id':identifier,'result_sha256':sha(raw),'result_chars':len(raw),
        'record_refs':records,'source_refs':sources,'derived':backends,'has_more':result.get('has_more',False),
        'next_offset':result.get('next_offset'),'reading_level':'retrieval_references_only',
        'full_result_saved':True,'read_full_result':{'tool':'memory_read','id':identifier,'offset':0,'max_chars':2048},
        'instructions':'Full result preserved without trimming. Read selected MEM-/SRC- IDs for original material; read this RCL ID by next_offset for the complete original result, ranking and metadata. A reference is not source reading.'}


def read(broker,sid,args):
    identifier=args['id'];offset=args.get('offset',0);limit=args.get('max_chars',2048)
    if (not re.fullmatch(r'RCL-[a-f0-9]{32}',identifier) or type(offset) is not int or offset<0
            or type(limit) is not int or not 1<=limit<=4096 or args.get('revision',1)!=1):
        raise ValueError('recall_result_page_invalid')
    with broker.store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='recall_results'").fetchone():raise PermissionError('owned_recall_result_required')
        row=db.execute('SELECT * FROM recall_results WHERE profile_id=? AND id=? AND sid=?',(broker.store.profile,identifier,sid)).fetchone()
    if row is None:raise PermissionError('owned_recall_result_required')
    if sha(row['body'])!=row['sha256']:raise PermissionError('recall_result_integrity_failed')
    if broker.store.retrieval_basis(sid)!=row['basis']:raise PermissionError('recall_basis_changed_refresh_required')
    if offset>len(row['body']):raise ValueError('recall_result_offset_outside_body')
    text=row['body'][offset:offset+limit];end=offset+len(text);more=end<len(row['body'])
    return {'contract':'BNNRecallPageV1','id':identifier,'revision':1,'result_sha256':row['sha256'],
        'total_chars':len(row['body']),'offset':offset,'text':text,'fragment_sha256':sha(text),
        'has_more':more,'next_offset':end if more else None,'reading_level':'exact_saved_retrieval_result_page',
        'source_reading_credit':False,'evidence_status':'unreviewed'}
