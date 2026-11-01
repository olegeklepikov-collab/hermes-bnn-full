"""Immutable, host-selected resources for one native leaf assignment."""
import json,re
from pathlib import Path
from bn_memory.store import canonical,sha

def install(db):
    db.execute('CREATE TABLE IF NOT EXISTS assignment_resources(profile_id TEXT,id TEXT,body TEXT,sha256 TEXT,PRIMARY KEY(profile_id,id))')

def prepare(host,parent,role,identifier,resources,persist=True):
    if resources is None:resources={}
    if not isinstance(resources,dict) or set(resources)-{'files','code','records','documents','library','data'}:raise ValueError('assignment_resources_invalid')
    if any(not isinstance(items,list) or len(items)>256 or any(not isinstance(item,str) for item in items) for items in resources.values()):raise ValueError('split_assignment_resources_required')
    selected={'files':{},'code':{},'records':{},'documents':{},'library':{},'data':{}}
    from bn_memory.source_visibility import hash_file,Visibility
    visibility=Visibility(host.store)
    from bn_memory import record_metadata
    candidate={'readonly':True,'role':role,'assignment_id':identifier,'project':host.store.binding(parent)['project'],'task':host.store.binding(parent)['task']}
    for kind in ['files','code']:
        for path in resources.get(kind,[]):
            _,target=host.store.safe_file(parent,path)
            if not target.is_file():raise PermissionError('assigned_regular_file_required')
            digest=hash_file(target)
            with host.store.db() as db:policy,_=visibility.policy(db,digest);record_metadata.enforce(candidate,policy)
            selected[kind][str(target)]={'sha256':digest}
    for identifier_ in resources.get('records',[]):
        row=host.store.read(parent,identifier_)
        with host.store.db() as db:record_metadata.enforce(candidate,record_metadata.read(db,row['id'],row['revision']))
        selected['records'][row['id']]={k:row[k] for k in ['revision','content_hash']}
    for did in resources.get('documents',[]):
        row=host.document_store().source(parent,did)
        digest=row['sha256']
        with host.store.db() as db:policy,_=visibility.policy(db,digest);record_metadata.enforce(candidate,policy)
        selected['documents'][did]={'sha256':digest,'corpus':row['corpus']}
    if resources.get('library'):
        from bn_memory.library import Library
        library=Library(host.broker)
        for key in resources['library']:
            value=library.dispatch(parent,{'action':'item','key':key})
            with host.store.db() as db:policy,_=visibility.policy(db,value['source_sha256']);record_metadata.enforce(candidate,policy)
            selected['library'][key]={'sha256':value['source_sha256']}
            if value['data']['data'].get('itemType')=='attachment':
                digest=hash_file(library.path(key))
                with host.store.db() as db:policy,_=visibility.policy(db,digest);record_metadata.enforce(candidate,policy)
                selected['library'][key]['file_sha256']=digest
    if resources.get('data'):
        from bn_memory.working_beads import lookup
        for bead in resources['data']:selected['data'][bead]=lookup(host.config,bead)
    raw=canonical(selected)
    if persist:
        with host.store.db() as db:
            install(db);db.execute('INSERT INTO assignment_resources VALUES(?,?,?,?)',(host.store.profile,identifier,raw,sha(raw)))
    return selected

def read(store,binding):
    if not binding['readonly'] or not store.config.get('w3_enabled'):return None
    with store.db() as db:
        row=db.execute('SELECT body,sha256 FROM assignment_resources WHERE profile_id=? AND id=?',(store.profile,binding['assignment_id'])).fetchone()
    if not row or sha(row[0])!=row[1]:raise PermissionError('native_assignment_resources_required')
    return json.loads(row[0])

def require(store,sid,kind,key):
    binding=store.binding(sid);selected=read(store,binding)
    if selected is None:return None
    value=selected[kind].get(key)
    if value is None:raise PermissionError('resource_not_assigned_to_native_child')
    return value

def record(store,sid,identifier,revision=None,content_hash=None):
    value=require(store,sid,'records',identifier)
    if value is not None and (revision is not None and revision!=value['revision'] or content_hash is not None and content_hash!=value['content_hash']):raise PermissionError('assigned_primary_version_changed')

def file(store,sid,target,kind='files'):
    value=require(store,sid,kind,str(target))
    if value is not None:
        from bn_memory.source_visibility import hash_file
        if hash_file(target)!=value['sha256']:raise PermissionError('assigned_file_version_changed')
    return value

def sql_filter(binding):
    if '_assigned_records' not in binding:return '',[]
    return ' AND r.id IN (SELECT key FROM json_each(?))',[canonical(binding['_assigned_records'])]
