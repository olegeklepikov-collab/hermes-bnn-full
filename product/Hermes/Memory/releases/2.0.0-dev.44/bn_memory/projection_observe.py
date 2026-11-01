"""Read-only native observation of an exact projection. Absence without an authoritative read is unknown."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bn_memory.store import sha
from bn_memory.embedding_contract import space

async def observe(cfg,backend,row):
    expected=(row['revision'],row['content_hash']);deleted=row['status']=='retracted'
    if backend=='graphiti':
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        d=Neo4jDriver(uri=cfg['neo4j_uri'],user=cfg['neo4j_user'],password=Path(cfg['neo4j_password_file']).read_text(),database='neo4j')
        try:
            result=await d.execute_query('MATCH (n:BNMemory {key:$key}) RETURN n.revision AS revision,n.content_hash AS content_hash,n.content AS content,n.active AS active',params={'key':sha(row['scope']+':'+row['id'])})
            values=[dict(x) for x in result.records]
            match=len(values)==1 and (values[0]['revision'],values[0]['content_hash'])==expected and values[0]['active']==(not deleted) and sha(values[0]['content'])==row['content_hash']
        finally:await d.close()
    elif backend=='zvec':
        import zvec
        path=Path(cfg['state_root'])/'embedding-spaces'/space(cfg)['space_id']/'zvec'/sha(row['scope'])[:24]
        if not path.is_dir():
            if not deleted:return {'matched':False,'reason':'native_collection_unavailable'}
            match=Path(cfg['state_root']).is_dir()
        else:
            collection=zvec.open(str(path))
            try:
                obj=collection.fetch(row['id']).get(row['id'])
                match=(obj is None) if deleted else (obj is not None and (obj.fields.get('revision'),obj.fields.get('content_hash'))==expected)
            finally:collection.close()
    elif backend=='agentmemory':
        from bn_memory.workers import http
        from urllib.parse import urlencode
        group='bn-memory-'+sha(row['scope']+':'+space(cfg)['space_id'])[:24];offset=0;matching=[]
        while True:
            data=http(cfg['agentmemory_url']+'/agentmemory/memories?'+urlencode({'agentId':group,'latest':'true','limit':500,'offset':offset}),token=cfg['agentmemory_key_file'])
            records=data['memories']
            for memory in records:
                try:value=json.loads(memory['content'])
                except (ValueError,KeyError,TypeError):continue
                if memory.get('project')==group and value.get('id')==row['id'] and value.get('scope')==row['scope']:matching.append((memory,value))
            offset+=len(records)
            if offset>=data['total']:break
            if not records:raise RuntimeError('native_memory_enumeration_did_not_advance')
        if deleted:match=not matching
        else:
            current=[(m,v) for m,v in matching if (v.get('revision'),v.get('content_hash'))==expected]
            spans=sorted({tuple(v['text_range']) for _,v in current});cursor=0
            for start,end in spans:
                if start!=cursor:break
                cursor=end
            match=bool(current) and cursor==len(row['content']) and all(row['content'][v['text_range'][0]:v['text_range'][1]]==v['content'] for _,v in current)
            if match:
                for memory,_ in current:
                    point=http(cfg['agentmemory_url']+'/agentmemory/memories/'+memory['id'],token=cfg['agentmemory_key_file'])
                    if point.get('bnn_vector',{}).get('present') is not True or point['bnn_vector'].get('dimensions')!=1024:match=False;break
    else:raise ValueError('projection_backend_not_supported')
    result={'matched':bool(match),'backend':backend,'id':row['id'],'revision':row['revision'],'content_hash':row['content_hash'],
            'status':('deleted' if deleted else 'indexed') if match else 'unknown','readback_verified':bool(match),'observation':'native exact point or complete owned-scope enumeration','projection_target':cfg['projection_targets'][backend]}
    if backend=='agentmemory' and not deleted and match:result['memory_ids']=[m['id'] for m,_ in current]
    if backend=='zvec':result['space_id']=space(cfg)['space_id']
    return result

if __name__=='__main__':
    req=json.load(sys.stdin)
    try:print(json.dumps(asyncio.run(observe(req['config'],req['backend'],req['record']))))
    except Exception as exc:print(json.dumps({'matched':False,'error_class':type(exc).__name__}));raise SystemExit(2)
