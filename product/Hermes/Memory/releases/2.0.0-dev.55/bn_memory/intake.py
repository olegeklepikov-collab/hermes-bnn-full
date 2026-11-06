"""One deterministic intake executor and one authoritative document ledger for every consumer."""
import json
from pathlib import Path
from bn_memory.documents import Documents
from bn_memory.store import sha

def addressed_unit(broker,sid,path,request_id,scope='project',unit=0):
    if type(unit) is not int or unit<0:raise ValueError('document_unit_invalid')
    docs=Documents(broker);catalogue=docs.catalogue(sid,{'path':path,'request_id':request_id,'scope':scope,'required_phases':['read']})
    cid=catalogue['corpus_id']
    with broker.store.db() as db:rows=db.execute('SELECT id FROM document_sources WHERE corpus=? ORDER BY id',(cid,)).fetchall()
    if len(rows)!=1:raise ValueError('one_document_per_addressed_intake_required')
    did=rows[0][0];row=docs.source(sid,did)
    if row['status']!='extracted':
        result=docs.extract(sid,{'doc_id':did})
        if result['status']!='extracted':return {'status':'document_intake_pending','doc_id':did,'corpus_id':cid,'next_action':'document_extract','indexed':False,'claims_accepted':False}
    row=docs.source(sid,did)
    with broker.store.db() as db:
        entry=db.execute('SELECT body FROM document_units WHERE doc=? AND unit=?',(did,unit)).fetchone()
        total=db.execute('SELECT count(*) FROM document_units WHERE doc=?',(did,)).fetchone()[0]
    if not entry:raise ValueError('document_unit_not_found')
    info=json.loads(entry[0]);base=Path(row['metadata']['parse_output'])
    from bn_memory.source_visibility import read_file,Visibility
    Visibility(broker.store).verify_snapshot(row['metadata']['snapshot'],row['sha256'])
    raw,_=read_file(base/(str(unit)+'.txt'));text=raw.decode('utf-8')
    if sha(text)!=info['text_sha256']:raise ValueError('document_unit_integrity_failed')
    return {'status':'unit_extracted','text':text,'unit':unit,'units_total':total,'locator':info['locator'],'doc_id':did,'corpus_id':cid,
            'original_sha256':row['sha256'],'original_path':row['metadata']['snapshot'],'format':row['format'],
            'unit_text_sha256':info['text_sha256'],'visual_required':info.get('visual_required',False),'visual_path':str(base/(str(unit)+'.png')) if info.get('visual_required') else None,
            'model_read':False,'claims_accepted':False}
