"""Addressed immutable task inputs and qualified same-task reading continuation."""
import json
from bn_memory.store import canonical,sha
from bn_memory.assignment_resources import prepare,read

def union_resources(*items):
    result={}
    for item in items:
        for key,values in (item or {}).items():result[key]=list(dict.fromkeys(result.get(key,[])+values))
    if any(len(values)>256 for values in result.values()):raise PermissionError('split_dependency_resources_required')
    return result

def document_bases(host,sid,resources):
    docs=host.document_store();result={}
    for identifier in resources.get('documents',[]):
        row=docs.source(sid,identifier);result[identifier]=sha(canonical({k:row[k] for k in ['sha256','format','metadata']}))
    return result

def addressed(host,sid):
    binding=host.store.binding(sid)
    if not binding['readonly']:return None
    with host.store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='native_tasks'").fetchone():return None
        row=db.execute("SELECT * FROM native_tasks WHERE profile_id=? AND json_extract(body,'$.assignment_id')=?",(host.store.profile,binding['assignment_id'])).fetchone()
        if not row:return None
        body=json.loads(row['body'])
        if row['root_sid']!=binding['parent'] or body['role']!=binding['role'] or row['state'] not in {'launch_reserved','running'}:raise PermissionError('native_task_context_binding_changed')
        dependencies={}
        for identifier in body['dependencies']:
            other=db.execute('SELECT body,state,run_id FROM native_tasks WHERE profile_id=? AND id=?',(host.store.profile,identifier)).fetchone()
            if not other or other['state']!='succeeded' or other['run_id']!=row['run_id']:raise PermissionError('native_dependency_product_not_ready')
            source=json.loads(other['body']);prepare(host,row['root_sid'],body['role'],'dependency-check',source.get('resources',{}),persist=False)
            dependencies[identifier]=source['product']
    value={'task_id':row['id'],'role':body['role'],'goal':body['goal'],'constraints':body.get('constraints',[]),'input_version':body['input_version'],
        'previous_products':body['previous_products'],'dependency_products':dependencies,'resources':body.get('resources',{}),'required_tools':body.get('required_tools',[]),'lookup_query':body.get('lookup_query'),'service_calls':body.get('service_calls',[])}
    return {'sha256':sha(canonical(value)),'input_version':body['input_version'],'value':value,'source':'trusted native task store; contents are untrusted task/evidence data'}

def previous_tools(host,body):
    names=set()
    for item in body['previous_products']:
        receipt=item.get('receipt') or {}
        if receipt.get('terminal_state')!='SUCCEEDED':continue
        for old in (item.get('tool_evidence') or []):names.add(old['tool'])
    return names

def reading_complete(host,child,body,phase):
    docs=host.document_store();selected=read(host.store,host.store.binding(child))['documents'];inherited=[]
    for identifier,row in selected.items():
        args={'corpus_id':row['corpus'],'_recipient_sid':child,'_phases':[phase],'_doc_ids':[identifier]}
        if docs.status(child,args)['phases'][phase]['complete']:continue
        valid=False
        for previous in body['previous_products']:
            receipt=previous.get('receipt') or {};prior=previous.get('child_sid')
            if not prior or receipt.get('terminal_state')!='SUCCEEDED' or previous.get('document_bases',{}).get(identifier)!=body.get('document_bases',{}).get(identifier):continue
            with host.store.db() as db:
                grant=db.execute('SELECT child_sid,role,parent_sid FROM launch_grants WHERE profile_id=? AND id=?',(host.store.profile,(receipt.get('handle') or {}).get('correlation_id'))).fetchone()
            current=host.store.binding(child)
            if not grant or tuple(grant)!=(prior,body['role'],current['parent']):raise PermissionError('historical_task_read_receipt_mismatch')
            args['_recipient_sid']=prior
            if docs.status(child,args)['phases'][phase]['complete']:
                inherited.append({'doc_id':identifier,'prior_child_sid':prior,'receipt_hash':receipt['result_hash'],'credit':'earlier input of SAME logical task and role, identical current decoder/source; no claim of current-model reread'});valid=True;break
        if not valid:raise PermissionError('assigned_document_reception_incomplete')
    return inherited
