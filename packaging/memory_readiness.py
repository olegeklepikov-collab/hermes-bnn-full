"""Read-only memory readiness. Presence, configuration and live identity are distinct.

This operator diagnostic never starts services, imports a model runtime, resets an
unknown outcome, alters source classifications, or treats TCP as a health proof.
"""
from pathlib import Path
import argparse,hashlib,json,socket,sqlite3
from urllib.parse import urlsplit

def database(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('existing_regular_database_required')
    c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN');return c

def rows(c,sql):return [dict(r) for r in c.execute(sql)]

def cognee_binding(instance,documents,datasets,root=None):
    """No source text or UUID-based authority is manufactured by observation."""
    names=set(datasets);result=[]
    for doc in documents:
        expected=instance+'-'+hashlib.sha256(doc['scope'].encode()).hexdigest()[:24]
        own=doc['dataset']==expected;present=doc['dataset'] in names
        local=Path(doc['text_path']).is_relative_to(Path(root).resolve()) if root is not None else None
        result.append({'doc_id':doc['id'],'ledger_status':doc['status'],
                       'instance_binding_matches':own,'native_dataset_present':present,'text_path_inside_current_instance':local,
                       'projection_verified':False,
                       'required_action':'observe_exact_native_item' if own and present and local is not False else 'explicit_projection_rebind_and_rebuild'})
    return result

def local_endpoint(uri,default_port=None):
    p=urlsplit(uri)
    if p.hostname!='127.0.0.1' or p.username or p.password:raise ValueError('local_service_endpoint_required')
    return p.hostname,p.port or default_port

def listening(uri,default_port=None):
    host,port=local_endpoint(uri,default_port)
    if not isinstance(port,int) or not 1<=port<=65535:raise ValueError('port_required')
    with socket.socket() as s:
        s.settimeout(1);errno=s.connect_ex((host,port))
    return {'port':port,'tcp_connect_errno':errno,'status':'listening_identity_unverified' if errno==0 else 'unavailable',
            'service_health_verified':False}

def inspect(root,probe=True):
    root=Path(root).resolve();cfg=json.loads((root/'Memory/settings.json').read_text())
    if Path(cfg['profile_home']).resolve()!=root/'data':raise ValueError('root_profile_mismatch')
    out={'contract':'BNNMemoryReadinessV1','mutation_performed':False,'new_provider_calls':0,
         'readiness_is_not_release_admission':True,'cross_database_atomic_snapshot':False}
    c=database(Path(cfg['state_root'])/'memory.sqlite')
    try:
        out['primary']={'quick_check':[r[0] for r in c.execute('PRAGMA quick_check')],
                        'records':c.execute('SELECT COUNT(*) FROM records').fetchone()[0],
                        'current':c.execute('SELECT COUNT(*) FROM current').fetchone()[0]}
        out['classifications']=rows(c,"SELECT json_extract(m.attributes,'$.horizon') AS horizon,json_extract(m.attributes,'$.memory_type') AS memory_type,COUNT(*) AS n FROM record_metadata m JOIN current u USING(id,revision) GROUP BY horizon,memory_type")
        out['projections']=rows(c,'SELECT backend,status,COUNT(*) AS n FROM outbox JOIN current USING(id,revision) GROUP BY backend,status')
        out['embedding_attempts']=rows(c,'SELECT purpose,status,COUNT(*) AS n FROM embedding_attempts GROUP BY purpose,status')
        out['source_chunks']=rows(c,'SELECT state,COUNT(*) AS n FROM semantic_chunks GROUP BY state')
        docs=rows(c,"SELECT id,scope,dataset,status,text_path FROM knowledge_docs WHERE status='indexed'")
        names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'intake_%'")]
        out['intake']={'rows':{n:c.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0] for n in names},
                       'empty_is_not_a_runtime_failure':True}
    finally:c.rollback();c.close()
    cr=Path(cfg['cognee_root']);instance=json.loads((cr/'state/instance.json').read_text())['instance_id']
    c=database(cr/'state/engine-dataset-isolation-v2/system/databases/cognee_db')
    try:
        out['cognee']={'bindings':cognee_binding(instance,docs,[r[0] for r in c.execute('SELECT name FROM datasets')],root),
                       'native_raw_items':c.execute('SELECT COUNT(*) FROM data').fetchone()[0]}
    finally:c.rollback();c.close()
    out['retrieval']={'automatic_mode':'hybrid' if cfg.get('semantic_context') else 'lexical',
                      'choice_requires_quality_evidence':True,'legacy_udr_index_enabled':cfg.get('udr_index_enabled')}
    out['services']={}
    if probe:
        for name,uri,port in [('agentmemory',cfg['agentmemory_url'],80),('neo4j',cfg['neo4j_uri'],7687)]:
            out['services'][name]=listening(uri,port)
        identity=json.loads((Path(cfg['zotero_root'])/'identity.json').read_text())
        out['services']['zotero']=listening(identity['base_url'],80)
    out['decisions_not_automatic']=['No blanket reclassification','No inferred event/expiry dates',
        'No unknown-outcome replay','No Graphiti expansion merely to duplicate Cognee',
        'No enable-all Intake rule','No production service startup from this diagnostic']
    return out

def main():
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--output',type=Path);a.add_argument('--no-probe',action='store_true');v=a.parse_args()
    result=inspect(v.root,not v.no_probe);raw=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if v.output:v.output.write_text(raw)
    else:print(raw,end='')
if __name__=='__main__':main()
