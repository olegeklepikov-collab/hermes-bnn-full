"""Narrow delegation of registered own inputs; explicit policies always win.

The operator enables this capability. A parent must still name the exact resource
for this one leaf. Neither unassigned files nor explicitly private/holdout data
gain authority from an analytical prompt.
"""
import json
from pathlib import Path
from bn_memory.store import canonical,sha


def artifact(store,db,target,digest):
    if not store.config.get('delegate_registered_sources',False):return None
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='result_artifacts'").fetchone():return None
    from bn_memory.path_relocation import operating_path
    for row in db.execute('SELECT id,body FROM result_artifacts WHERE profile_id=?',(store.profile,)):
        body=json.loads(row['body'])
        if (body.get('authority')=='owner_registered_project' and body.get('sha256')==digest
                and operating_path(store.config,body['source_path'])==Path(target)):
            return row['id']
    return None


def delegated(role,reference):
    return {'contract':'BNAttachedSourceDelegationV1','role':role,'registration':reference,
            'visibility':{'allowed_roles':[role],'evidence_use':'general'}}


def effective(store,db,binding,digest,policy,revision):
    if revision or not binding['readonly'] or not store.config.get('delegate_registered_sources',False):return policy
    row=db.execute('SELECT body,sha256 FROM assignment_resources WHERE profile_id=? AND id=?',
                   (store.profile,binding['assignment_id'])).fetchone()
    if not row or sha(row['body'])!=row['sha256']:return policy
    resources=json.loads(row['body'])
    for kind in ['files','code','documents']:
        for item in resources.get(kind,{}).values():
            value=item.get('source_delegation')
            if (item.get('sha256')==digest and isinstance(value,dict)
                    and value.get('contract')=='BNAttachedSourceDelegationV1'
                    and value.get('role')==binding['role']):
                return {'visibility':value['visibility'],'source_dependencies':[]}
    return policy
