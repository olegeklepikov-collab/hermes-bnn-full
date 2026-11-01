"""Pinned native backends. No autonomous model, arbitrary query or shell execution."""
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def hashtext(text):return hashlib.sha256(text.encode()).hexdigest()

def http(url,body=None,token=None,timeout=8):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+Path(token).read_text().strip()
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    if token:
        class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                raise PermissionError('credential_redirect_denied')
        with urllib.request.build_opener(NoCredentialRedirect()).open(req,timeout=timeout) as response:return json.load(response)
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def agentmemory(config,operation,payload):
    base=config['agentmemory_url']
    def api(path,body=None):return http(base+path,body,config.get('agentmemory_key_file'),timeout=45)
    from bn_memory.embedding_contract import space
    semantic_space=space(config)['space_id']
    def group_for(scope):return 'bn-memory-'+hashtext(scope+':'+semantic_space)[:24]
    if operation=='health':return api('/agentmemory/health')
    if operation=='search':
        if 'record_allowlist' in payload:
            from bn_memory.vector_visibility import allowlist
            from urllib.parse import quote
            allowed=allowlist(payload['record_allowlist'],payload['scopes']);results=[]
            for selected in allowed:
                for identifier in payload.get('native_ids',{}).get(selected['id'],[]):
                    observed=api('/agentmemory/memories/'+quote(identifier,safe=''));memory=observed['memory'];value=json.loads(memory['content'])
                    if any(value.get(k)!=selected[k] for k in ['id','revision','content_hash','scope']) or memory.get('project')!=group_for(selected['scope']):raise PermissionError('native_memory_point_outside_assignment')
                    if observed.get('bnn_vector',{}).get('present') is not True:raise PermissionError('native_assigned_memory_vector_missing')
                    if payload['query'].casefold() in value.get('content','').casefold():results.append(selected);break
            return {'records':results[:10],'backend':'agentmemory','prefiltered':True,'method':'assigned_native_point_reads_lexical','remote_embedding_called':False}
        results=[]
        for scope in payload['scopes']:
            group=group_for(scope)
            r=api('/agentmemory/search',{'query':payload['query'],'project':group,'agentId':group,'limit':50,'format':'full'})
            for row in r.get('results',[]):
                item=row.get('observation',row);content=item.get('content') or item.get('narrative','')
                try:v=json.loads(content)
                except (ValueError,TypeError):continue
                if v.get('scope')==scope and v.get('id','').startswith('MEM-'):results.append(v)
        return {'records':results,'backend':'agentmemory'}
    row=payload['record'];group=group_for(row['scope'])
    previous=payload.get('previous',{})
    previous_ids=previous.get('memory_ids',[]) or ([previous['memory_id']] if previous.get('memory_id') else [])
    # Prior-generation receipts may lack IDs. Enumerate the exact owned namespace before replacement/deletion.
    from urllib.parse import urlencode
    offset=0;found=[]
    while True:
        page=api('/agentmemory/memories?'+urlencode({'agentId':group,'limit':500,'offset':offset}))
        items=page['memories']
        for item in items:
            try:value=json.loads(item.get('content',''))
            except (ValueError,TypeError):continue
            if item.get('project')==group and value.get('id')==row['id'] and value.get('scope')==row['scope']:found.append(item['id'])
        offset+=len(items)
        if offset>=page['total']:break
        if not items:raise RuntimeError('native_memory_enumeration_stalled')
    previous_ids=sorted(set(previous_ids+found))
    for identifier in previous_ids:
        if identifier not in found:
            try:old=api('/agentmemory/memories/'+identifier)['memory']
            except urllib.error.HTTPError as exc:
                if exc.code==404:continue
                raise
            try:identity=json.loads(old['content'])
            except (ValueError,KeyError,TypeError):raise PermissionError('prior_memory_identity_unknown')
            if old.get('project')!=group or identity.get('id')!=row['id'] or identity.get('scope')!=row['scope']:raise PermissionError('prior_memory_outside_owned_record')
        api('/agentmemory/forget',{'memoryId':identifier})
    if row['status']=='retracted':return {'status':'deleted','backend':'agentmemory','space_id':semantic_space,'revision':row['revision'],'content_hash':row['content_hash']}
    ids=[];ranges=[]
    for start in range(0,len(row['content']),6000):
        end=min(start+6000,len(row['content']));part={k:row[k] for k in ['id','revision','scope','content_hash','source']}
        part.update(content=row['content'][start:end],text_range=[start,end],total_chars=len(row['content']),space_id=semantic_space)
        content=json.dumps(part,ensure_ascii=False)
        if len(content.encode('utf-16-le'))//2+100>16000:raise ValueError('addressed_agentmemory_envelope_too_large')
        result=api('/agentmemory/remember',{'content':content,'project':group,'agentId':group,'concepts':json.loads(row['concepts'])})
        memory=result.get('memory',{})
        if memory.get('content')!=content or memory.get('agentId')!=group or memory.get('project')!=group:raise RuntimeError('agentmemory_readback_mismatch')
        observed=api('/agentmemory/memories/'+memory['id'])
        if observed.get('memory',{}).get('content')!=content or observed.get('bnn_vector',{}).get('present') is not True or observed['bnn_vector'].get('dimensions')!=1024:raise RuntimeError('agentmemory_native_vector_not_confirmed')
        ids.append(memory['id']);ranges.append([start,end])
    return {'status':'indexed','backend':'agentmemory','memory_ids':ids,'indexed_ranges':ranges,'total_chars':len(row['content']),
            'space_id':semantic_space,'content_hash':row['content_hash'],'revision':row['revision'],'readback_verified':True,'native_vector_readback':True}

async def graphiti_async(config,operation,payload):
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    d=Neo4jDriver(uri=config['neo4j_uri'],user=config['neo4j_user'],password=Path(config['neo4j_password_file']).read_text().strip(),database='neo4j')
    def rows(value):return [dict(x) for x in value.records]
    try:
        await d.health_check()
        if operation=='health':return {'status':'healthy','backend':'graphiti_core.Neo4jDriver','mode':'typed_provenance_graph'}
        if operation=='search':
            if 'record_allowlist' in payload:
                from bn_memory.vector_visibility import allowlist
                permitted=allowlist(payload['record_allowlist'],payload['scopes'])
                r=await d.execute_query('UNWIND $allowed AS a MATCH (m:BNMemory {id:a.id}) WHERE m.scope IN $scopes AND m.active=true AND m.revision=a.revision AND m.content_hash=a.content_hash AND toLower(m.content) CONTAINS toLower($query) RETURN m.id AS id,m.revision AS revision,m.content_hash AS content_hash,m.scope AS scope ORDER BY m.id LIMIT 10',params={'allowed':permitted,'scopes':payload['scopes'],'query':payload['query']})
                return {'records':rows(r),'backend':'graphiti/neo4j','prefiltered':True}
            r=await d.execute_query('MATCH (m:BNMemory) WHERE m.scope IN $scopes AND m.active=true '
                'AND (toLower(m.content) CONTAINS toLower($query) OR EXISTS { MATCH (m)-[:MENTIONS]->(t:BNMemoryTopic) WHERE toLower(t.name) CONTAINS toLower($query) }) '
                'OPTIONAL MATCH (m)-[:MENTIONS]->(t:BNMemoryTopic) RETURN m.id AS id,m.revision AS revision,m.content_hash AS content_hash,m.scope AS scope,collect(t.name) AS concepts ORDER BY m.id LIMIT 10',params=payload)
            return {'records':rows(r),'backend':'graphiti/neo4j'}
        row=payload['record'];key=hashtext(row['scope']+':'+row['id']);params={k:row[k] for k in ['id','revision','scope','content','content_hash','source']};params['key']=key
        await d.execute_query('MERGE (m:BNMemory {key:$key}) SET m.id=$id,m.revision=$revision,m.scope=$scope,m.content=$content,m.content_hash=$content_hash,m.source=$source,m.active=$active',params={**params,'active':row['status']=='recorded'})
        await d.execute_query('MATCH (m:BNMemory {key:$key})-[r:MENTIONS]->() DELETE r',params={'key':key})
        if row['status']=='recorded':
            for concept in json.loads(row['concepts']):
                await d.execute_query('MATCH (m:BNMemory {key:$key}) MERGE (t:BNMemoryTopic {key:$topic_key}) SET t.name=$name,t.scope=$scope MERGE (m)-[r:MENTIONS]->(t) SET r.revision=$revision,r.provenance=$source',params={**params,'topic_key':hashtext(row['scope']+':'+concept),'name':concept})
        r=await d.execute_query('MATCH (m:BNMemory {key:$key}) RETURN m.revision AS revision,m.content_hash AS content_hash,m.active AS active',params={'key':key});verified=rows(r)
        if not verified or verified[0]['content_hash']!=row['content_hash'] or verified[0]['revision']!=row['revision']:raise RuntimeError('graph_readback_mismatch')
        return {'status':'indexed' if row['status']=='recorded' else 'deleted','backend':'graphiti/neo4j','revision':row['revision'],'content_hash':row['content_hash'],'readback_verified':True,'inferred_relations':False}
    finally:await d.close()

def zvec(config,operation,payload):
    import zvec as zv
    from bn_memory.embedding_contract import space
    embedding_space=space(config)['space_id']
    if payload.get('space_id')!=embedding_space:raise PermissionError('vector_space_mismatch')
    if operation=='health':return {'status':'healthy','version':zv.__version__,'model':'voyage-4-large','dimensions':1024}
    filtered=operation=='search' and 'record_allowlist' in payload
    if filtered:
        from bn_memory.vector_visibility import allowlist,predicates,native_contract,ranked
        from bn_memory.embeddings import Embeddings
        allowed=allowlist(payload['record_allowlist'],payload['scopes'])
        if payload.get('source_scopes'):raise PermissionError('child_vector_sources_not_qualified')
        Embeddings.vector(payload['vector']);ranked([],payload.get('topk',10))
        if not allowed:return {'records':[],'backend':'zvec','status':'queried','prefiltered':True,'eligible':0,'filter_batches':0,'collections':0,'metric':'inner_product'}
    filter_batches=0;collections=0
    batches=[]
    if operation=='search':
        batches=([('memory',scope,None) for scope in payload['scopes'] if any(r['scope']==scope for r in allowed)] if filtered else [('memory',scope,None) for scope in payload['scopes']]+[('sources',scope,None) for scope in payload.get('source_scopes',[])])
    else:
        records=payload.get('records') if operation=='sync_many' else [payload['record']]
        grouped={}
        for row in records:grouped.setdefault(row['scope'],[]).append(row)
        batches=[(payload.get('collection_kind','memory'),scope,rows) for scope,rows in grouped.items()]
    results=[]
    for kind,scope,rows in batches:
        if kind not in {'memory','sources'}:raise ValueError('vector_collection_kind_invalid')
        root=Path(config['state_root'])/'embedding-spaces'/embedding_space/('zvec-sources' if kind=='sources' else 'zvec');root.mkdir(parents=True,exist_ok=True)
        path=root/hashtext(scope)[:24]
        if not path.exists():
            if operation=='search':continue
            schema=zv.CollectionSchema(name='bn_memory',vectors=[zv.VectorSchema('embedding',zv.DataType.VECTOR_FP32,1024)],fields=[zv.FieldSchema('record_id',zv.DataType.STRING),zv.FieldSchema('revision',zv.DataType.INT64),zv.FieldSchema('content_hash',zv.DataType.STRING)])
            collection=zv.create_and_open(str(path),schema)
        else:collection=zv.open(str(path),zv.CollectionOption(read_only=operation=='search'))
        try:
            if operation=='search':
                if filtered:
                    native_contract(zv,collection);members=[r for r in allowed if r['scope']==scope]
                    queries=predicates(members);collections+=1
                else:queries=[None];collections+=1
                for predicate in queries:
                    if filtered:filter_batches+=1
                    for doc in collection.query(zv.Query(field_name='embedding',vector=payload['vector']),topk=payload.get('topk',10),**({'filter':predicate} if predicate is not None else {})):
                        results.append({'id':doc.fields['record_id'],'revision':doc.fields['revision'],'content_hash':doc.fields['content_hash'],'scope':scope,'score':doc.score,**({'kind':'source'} if kind=='sources' else {})})
            else:
                upserts=[]
                for row in rows:
                    if row['status']=='retracted':collection.delete(row['id'])
                    else:upserts.append(zv.Doc(id=row['id'],fields={'record_id':row['id'],'revision':row['revision'],'content_hash':row['content_hash']},vectors={'embedding':row.get('vector',payload.get('vector'))}))
                if upserts:collection.upsert(upserts)
                for row in rows:
                    if row['status']=='retracted':continue
                    fetched=collection.fetch(row['id']).get(row['id'])
                    if fetched is None or fetched.fields.get('content_hash')!=row['content_hash'] or fetched.fields.get('revision')!=row['revision']:raise RuntimeError('zvec_readback_failed')
                collection.flush()
        finally:collection.close()
    if filtered:
        results=ranked(results,payload.get('topk',10))
        return {'records':results,'backend':'zvec','status':'queried','prefiltered':True,'eligible':len(allowed),'filter_batches':filter_batches,'collections':collections,'metric':'inner_product','dimensions':1024,'space_id':embedding_space}
    return {'records':results,'backend':'zvec','status':'queried' if operation=='search' else 'indexed','dimensions':1024,'readback_verified':operation!='search','space_id':embedding_space,'collections':collections}

async def mcp_read(config,operation,payload):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    root=payload['project_root'];state=Path(config['state_root']);env=dict(os.environ)
    env['PATH']=config['code_path']
    if operation=='serena':
        import yaml
        # The project's .serena file is untrusted input and can contain an initialization command.
        # Use the pinned native folder-location setting, in an existing owner-only directory,
        # so Serena's fallback never consumes workspace configuration.
        ident=hashtext(root)[:24];home=state/'serena-homes'/ident;home.mkdir(parents=True,exist_ok=True,mode=0o700)
        project=state/'serena-projects'/ident;project.mkdir(parents=True,exist_ok=True,mode=0o700)
        base=state/'serena/serena_config.yml';global_config=yaml.safe_load(base.read_text()) if base.exists() else {}
        global_config.update({'projects':[],'project_serena_folder_location':str(project),'web_dashboard':False,'open_web_dashboard':False})
        (home/'serena_config.yml').write_text(yaml.safe_dump(global_config,sort_keys=False));(home/'serena_config.yml').chmod(0o600)
        language=['r'] if payload.get('code_language')=='r' else config.get('project_languages',{}).get(root,['python'])
        (project/'project.yml').write_text(yaml.safe_dump({'project_name':'bn-'+ident,'language_servers':language,'encoding':'utf-8','read_only':True,'initialization_command':None,'ignored_paths':['**/.env*','**/auth.json','**/mcp-tokens.json','**/.git/**','**/node_modules/**']}));(project/'project.yml').chmod(0o600)
        shared=state/'serena/language_servers';link=home/'language_servers'
        if shared.exists() and not link.exists():link.symlink_to(shared)
        env['SERENA_HOME']=str(home)
        command=config['serena_command'];args=['start-mcp-server','--transport','stdio','--project',root,'--mode','planning','--add-mode','no-memories','--enable-web-dashboard','false'];name=payload['tool'];arguments=payload['arguments']
    else:
        import yaml
        workspace=state/('mirage-'+hashtext(root)[:16]+'.yaml')
        workspace.write_text(yaml.safe_dump({'mode':'READ','runtimes':['vfs'],'mounts':{'/project':{'resource':'disk','mode':'READ','config':{'root':root}}}}));workspace.chmod(0o600)
        command=config['mirage_command'];args=['mcp',str(workspace)];name=payload['tool'];arguments=payload['arguments']
    with open(os.devnull,'w') as log:
        async with stdio_client(StdioServerParameters(command=command,args=args,env=env),errlog=log) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize();tool_list=await session.list_tools();tools={t.name:getattr(t,'input_schema',None) or getattr(t,'inputSchema',{}) for t in tool_list.tools}
                if name=='__describe__':return {'tools':tools}
                if name not in tools:raise ValueError('read_tool_unavailable')
                if operation=='mirage' and 'path' in arguments:
                    # Preserve exact source version; returned text is checked by the broker.
                    schema=tools[name];pathkey='path' if 'path' in schema.get('properties',{}) else 'virtual_path'
                    arguments={pathkey:arguments['path']}
                result=await session.call_tool(name,arguments)
                if getattr(result,'is_error',False) or getattr(result,'isError',False):raise RuntimeError('native_read_tool_error:'+str([getattr(c,'text','') for c in result.content])[:300])
                return {'backend':operation,'tool':name,'content':[c.text for c in result.content if getattr(c,'type','')=='text']}

def main():
    req=json.load(sys.stdin);config=req['config'];backend=req['backend'];operation=req['operation'];payload=req.get('payload',{})
    if backend=='agentmemory':result=agentmemory(config,operation,payload)
    elif backend=='graphiti':result=asyncio.run(graphiti_async(config,operation,payload))
    elif backend=='zvec':result=zvec(config,operation,payload)
    elif backend in {'serena','mirage'}:result=asyncio.run(mcp_read(config,backend,payload))
    else:raise ValueError('backend_not_allowed')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        def detail(e):
            return ' | '.join(detail(x) for x in e.exceptions) if isinstance(e,BaseExceptionGroup) else type(e).__name__+':'+str(e)[:200]
        print(json.dumps({'status':'unavailable','code':detail(exc)}));sys.exit(2)
