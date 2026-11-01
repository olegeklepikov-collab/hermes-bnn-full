"""Explicit report revision for signed Research/Foundation; original supplier files unchanged."""
import json,hashlib
from bn_memory.store import canonical,sha

def revise(research,sid,run,args):
    host=research.host;row,body=research.load(sid,run)
    host.modules.require(sid,'research');host.store.writable(sid)
    request=args['request_id'];fingerprint=sha(canonical(args));operation='RRV-'+sha(canonical([host.store.profile,run,request]))[:24]
    with host.store.db() as db:
        old=db.execute('SELECT state,input_hash,body FROM module_attempts WHERE profile_id=? AND id=?',(host.store.profile,operation)).fetchone()
    if old:
        if old['input_hash']!=fingerprint:raise ValueError('report_revision_request_conflict')
        if old['state']!='succeeded':raise PermissionError('report_revision_effects_require_observation')
        return {**json.loads(old['body']),'duplicate':True,'new_effects':0}
    if row['sid']!=sid or row['state'] not in {'partial','complete'}:raise PermissionError('owned_finished_report_required')
    if row['revision']!=args['expected_revision']:raise ValueError('report_revision_binding_conflict')
    if not args.get('reason','').strip():raise ValueError('report_revision_reason_required')
    from hermes_research_report.research_workspace import root_for,write_json
    root=root_for(run);report=root/'report.md';previous=body['report']
    digest=hashlib.sha256(report.read_bytes()).hexdigest()
    if digest!=args['report_sha256'] or digest!=previous['report_sha256']:raise PermissionError('previous_report_version_mismatch')
    with host.store.db() as db:
        if db.execute("SELECT 1 FROM native_tasks WHERE profile_id=? AND run_id=? AND state IN ('running','launch_reserved','unknown')",(host.store.profile,run)).fetchone():raise PermissionError('report_workers_not_quiescent')
        if db.execute("SELECT 1 FROM module_attempts WHERE profile_id=? AND sid=? AND module='research' AND state IN ('running','unknown')",(host.store.profile,sid)).fetchone():raise PermissionError('report_previous_effect_unsettled')
    task=research.tasks.get({'issue_id':body['bead']})['issue']
    if task.get('assignee')!=body['holder']:raise PermissionError('report_task_holder_changed')
    if task['status'] not in {'in_progress','closed'}:raise PermissionError('report_task_state_requires_observation')
    # Preserve the exact preceding report before any lease/task/state effect.
    archive=root/('host-report-'+digest+'.md')
    if archive.exists():
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=digest:raise PermissionError('previous_report_archive_corrupt')
    else:
        with archive.open('xb') as f:f.write(report.read_bytes());f.flush();__import__('os').fsync(f.fileno())
        archive.chmod(0o400)
    with host.store.db() as db:
        db.execute('INSERT INTO module_attempts VALUES(?,?,?,?,?,?,?,?)',(host.store.profile,sid,operation,'research',body['bead'],fingerprint,'running','{}'))
    try:
        if task['status']=='closed':research.tasks.effect(sid,operation+':reopen',[body['bead'],digest],lambda:research.tasks.run(['update',body['bead'],'--status','in_progress']))
        lease=research.runtime.acquire_lease({'schema_version':1,'work_id':body['bead'],'holder_id':body['holder'],'expected_revision':body['lease_revision'],'ttl_seconds':7200})
        if lease['status']!='acquired':raise PermissionError('report_revision_lease_conflict')
        revision=body.get('report_revision',1)+1
        body.setdefault('report_versions',[]).append({'revision':revision-1,'report':previous,'completion':body['completion'],'host_context':body['binding'],'host_run':body['host_run'],
            'archive_path':str(archive),'sha256':digest,'reason_for_next_revision':args['reason']})
        body.update(report_revision=revision,lease_revision=lease['current_revision'],host_run=body['host_run']+'-report-'+str(revision),report=None)
        body.pop('completion',None);body.pop('finalizing_lifecycle_id',None)
        research.put(body['project'],body['work_ref'],research.work(body,'active'),body['host_run'],sid)
        context=research.session(sid,body).prepare(body['question']);body['binding']=context['host_context'];body['context']=context
        saved=json.loads((root/'run.json').read_text());saved['host_context']=body['binding'];saved['host_report_revision']=revision;write_json(root/'run.json',saved)
        research.persist(run,sid,'active',body,row['revision'])
        result={'run_id':run,'bead_id':body['bead'],'state':'active','report_revision':revision,'previous_report_sha256':digest,'previous_report_path':str(archive),
                'new_host_context':body['binding'],'recollected_sources':0,'resource_usage_reset':False,'scientific_acceptance':False}
        with host.store.db() as db:db.execute("UPDATE module_attempts SET state='succeeded',body=? WHERE profile_id=? AND id=?",(canonical(result),host.store.profile,operation))
        return result
    except BaseException:
        with host.store.db() as db:db.execute("UPDATE module_attempts SET state='unknown' WHERE profile_id=? AND id=?",(host.store.profile,operation))
        raise
