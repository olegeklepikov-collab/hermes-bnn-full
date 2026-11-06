"""Read a Beads-linked immutable Dolt object; no arbitrary SQL or caller-selected storage root."""
import hashlib,json,re,subprocess
from pathlib import Path
from bn_memory.store import canonical,sha,SENSITIVE

def read(broker,sid,args):
    child=broker.store.binding(sid)['readonly']
    if child:
        if not broker.config.get('w3_enabled'):raise PermissionError('child_versioned_data_not_qualified')
        from bn_memory.assignment_resources import require
        expected=require(broker.store,sid,'data',args['bead_id'])
    from bn_memory.working_beads import lookup
    ref=lookup(broker.config,args['bead_id'])
    if child and ref!=expected:raise PermissionError('assigned_Beads_revision_changed')
    command=broker.config['working_beads']['command']
    task=json.loads(subprocess.run([command,'show',args['bead_id'],'--json'],capture_output=True,text=True,check=True,timeout=15).stdout)[0]
    if str(task.get('revision'))!=ref['revision']:raise RuntimeError('Beads_changed_during_dataset_lookup')
    value=task.get('metadata',{}).get(args.get('link_key','w2_dataset'))
    if not isinstance(value,dict):raise ValueError('Beads_versioned_data_link_not_found')
    required={'database','branch','commit_hash','project_id','object_id','content_hash','source_sha256'}
    if not required<=value.keys():raise ValueError('incomplete_versioned_data_reference')
    authority=broker.config.get('dolt_authorities',{}).get(value['database'])
    if not authority or value['branch']!=authority['branch']:raise PermissionError('Dolt_database_or_branch_not_authorized')
    for key,pattern in [('commit_hash',r'[0-9a-v]{32}'),('content_hash',r'[a-f0-9]{64}'),('source_sha256',r'[a-f0-9]{64}')]:
        if not isinstance(value[key],str) or not re.fullmatch(pattern,value[key]):raise ValueError('Dolt_link_hash_invalid')
    for key in ['object_id','project_id']:
        if not isinstance(value[key],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',value[key]):raise ValueError('Dolt_link_identifier_invalid')
    binary=Path(authority['executable']);root=Path(authority['root'])
    if binary.is_symlink() or not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest()!=authority['binary_sha256']:raise PermissionError('Dolt_executable_changed')
    def query(sql):
        result=subprocess.run([str(binary),'sql','-r','json','-q',sql],cwd=root,capture_output=True,text=True,timeout=30,check=True)
        return json.loads(result.stdout)['rows']
    if query('SELECT ACTIVE_BRANCH() AS branch')[0]['branch']!=value['branch']:raise PermissionError('Dolt_branch_changed')
    rows=query("SELECT object_json,content_hash FROM objects AS OF '"+value['commit_hash']+"' WHERE project_id='"+value['project_id']+"' AND object_id='"+value['object_id']+"'")
    if len(rows)!=1 or rows[0]['content_hash']!=value['content_hash']:raise RuntimeError('Dolt_version_reference_not_found')
    obj=rows[0]['object_json'];obj=json.loads(obj) if isinstance(obj,str) else obj
    if sha(canonical(obj))!=value['content_hash']:raise RuntimeError('Dolt_object_hash_mismatch')
    text=canonical(obj)
    if SENSITIVE.search(text):raise PermissionError('private_versioned_data_not_context')
    offset=args.get('offset',0);limit=args.get('limit',8192)
    if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=8192:raise ValueError('Dolt_data_page_invalid')
    return {'contract':'BNVersionedDataPageV1','Beads':ref,'reference':{k:value[k] for k in sorted(required)},'text':text[offset:offset+limit],
            'offset':offset,'next_offset':offset+limit if offset+limit<len(text) else None,'has_more':offset+limit<len(text),
            'total_chars':len(text),'source_sha256':value['source_sha256'],'reading_level':'exact_versioned_object_page','evidence_status':'unreviewed'}
