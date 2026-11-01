"""Host-only receipts for real isolated S/D calculations. Does not rewrite model products."""
import json

def collect(adapter,job_id):
    host=adapter.host;job=adapter.runtime.bridge.call('job_get',{'job_id':job_id})
    sid=job.get('child_session_id')
    if not sid or job['role'] not in {'S','D'}:raise PermissionError('GSD_compute_role_recipient_required')
    binding=host.store.binding(sid)
    if binding['role']!=job['role']:raise PermissionError('GSD_compute_role_mismatch')
    with host.store.db() as db:
        rows=db.execute("SELECT id FROM compute_jobs WHERE profile_id=? AND sid=? AND assignment_id=? AND state='completed' ORDER BY created,id",(host.store.profile,sid,binding['assignment_id'])).fetchall()
    from bn_memory.compute import Compute
    compute=Compute(host.broker);proofs=[]
    for row in rows:
        status=compute.view(sid,{'action':'status','job_id':row['id']});receipt=status['receipt']
        if not status['inputs_current'] or not receipt.get('os_isolation') or receipt.get('exit_code')!=0:continue
        output=compute.view(sid,{'action':'read','job_id':row['id'],'offset':0,'limit':8192})
        if output['has_more']:raise PermissionError('split_required_compute_proof_without_trimming')
        proofs.append({'contract':'GSDIsolatedComputeReceiptV1','native_job_id':job_id,'child_session_id':sid,
            'role':job['role'],'compute_job_id':row['id'],'receipt':receipt,'output_text':output['text'],
            'output_sha256':output['source_sha256'],'meaning_accepted':False,'scope':'Actual isolated execution on supplied inputs; not independent scientific confirmation'})
    if not proofs:raise PermissionError('required_GSD_compute_executor_did_not_produce_a_receipt')
    return proofs
