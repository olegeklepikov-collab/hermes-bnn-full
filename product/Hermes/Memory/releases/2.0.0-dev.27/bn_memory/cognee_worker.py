"""Pinned Cognee SDK only; native model/embedding provider must be supplied by the host."""
import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bn_memory import COGNEE_VERSION

def plain(value):
    if hasattr(value,'model_dump'):return value.model_dump(mode='json')
    if hasattr(value,'to_dict'):return value.to_dict()
    if dataclasses.is_dataclass(value):return dataclasses.asdict(value)
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(x) for x in value]
    return value

async def distill_with_evidence_closure(session_id,dataset):
    """Compose pinned SDK stages; preserve QA-grounded proposals' dependencies.

    SDK curator allows empty member IDs for QA-only proposals, whereas its
    writer requires member evidence. Supply actual gated session candidates
    as explicit supplementary dependencies, never as invented curator choices.
    Confidence/novelty/writer gates and SDK publication/watermark remain intact.
    """
    from cognee.modules.session_distillation import distill as sdk
    scope=await sdk.resolve_distillation_scope(session_id=session_id,dataset=dataset,user=None)
    entries=await sdk.load_distillable_context_entries(scope)
    if not entries:return plain(scope.result('no_gated_entries')),[]
    new=await sdk.select_undistilled_entries(scope,entries)
    if not new:return plain(scope.result('no_new_entries')),[]
    qa=await sdk.load_session_qa_rows(scope)
    proposed,failures=await sdk.propose_lessons(qa,entries)
    if failures:raise RuntimeError('mandatory_curator_failed')
    valid={e.id for e in entries};closed=[];adapted=[]
    for lesson in proposed:
        original=list(lesson.member_entry_ids)
        if set(original)-valid:raise RuntimeError('curator_dependency_outside_session')
        supplied=original or [e.id for e in entries]
        closed.append({'statement':lesson.working_statement,'curator_member_ids':original,'writer_dependency_ids':supplied,'supplemented_by_adapter':not bool(original)})
        adapted.append(lesson.model_copy(update={'member_entry_ids':supplied}))
    accepted,failures=await sdk.accept_proposed_lessons(scope,adapted,entries)
    if failures:raise RuntimeError('mandatory_writer_failed')
    documents=await sdk.publish_distilled_lessons(scope,accepted) if accepted else []
    await sdk.advance_distillation_watermark(scope,entries)
    status='completed' if documents else 'no_accepted_lessons' if proposed else 'no_proposed_lessons'
    return plain(scope.result(status,documents=documents)),closed

async def run(req):
    cfg=req['config'];root=Path(cfg['cognee_root']);runtime=req.get('runtime') or {};state=root/'state/engine-dataset-isolation-v2'
    if req['operation']=='lesson':
        import hashlib
        state=root/'state/lesson-engines'/hashlib.sha256(req['payload']['engine_scope'].encode()).hexdigest()[:24]
    state.mkdir(parents=True,exist_ok=True)
    if req['operation']=='parse_pdf':
        raise PermissionError('common_document_intake_required')
    env={'COGNEE_LOGS_DIR':str(root/'state/logs'),'COGNEE_REPOS_DIR':str(root/'state/repos'),'COGNEE_TRACING_ENABLED':'false','TELEMETRY_DISABLED':'true','COGNEE_SKIP_CONNECTION_TEST':'true','ENABLE_BACKEND_ACCESS_CONTROL':'true','AUTO_FEEDBACK':'false','ALLOW_CYPHER_QUERY':'false','LLM_PROVIDER':'custom','LLM_MODEL':'openai/gpt-6.1-sol','LLM_MAX_COMPLETION_TOKENS':'4096','LLM_STRUCTURED_OUTPUT_FRAMEWORK':'litellm_native','EMBEDDING_PROVIDER':'openai_compatible','EMBEDDING_MODEL':'voyage-4-large','EMBEDDING_DIMENSIONS':'1024','EMBEDDING_MAX_COMPLETION_TOKENS':'4096','EMBEDDING_BATCH_SIZE':'16','NO_PROXY':'127.0.0.1,localhost','GRAPH_DATABASE_PROVIDER':'ladybug','VECTOR_DB_PROVIDER':'lancedb','DB_PROVIDER':'sqlite','XDG_CACHE_HOME':str(root/'state/cache'),'HF_HOME':str(root/'state/cache/huggingface'),'IMPROVE_STAGES_DISABLED':'build_truth_subspace'}
    if runtime:
        env.update({'LLM_ENDPOINT':runtime['url'],'LLM_API_KEY':runtime['token'],'EMBEDDING_ENDPOINT':runtime['url'],'EMBEDDING_API_KEY':runtime['token']})
    else:
        env.update({'LLM_ENDPOINT':'http://127.0.0.1:1/v1','LLM_API_KEY':'unavailable','EMBEDDING_ENDPOINT':'http://127.0.0.1:1/v1','EMBEDDING_API_KEY':'unavailable'})
    os.environ.update(env)
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',LITELLM_LOCAL_MODEL_COST_MAP='True')
    if req['operation']=='lesson':
        os.environ['AUTO_FEEDBACK']='true'
    os.environ.update({'SYSTEM_ROOT_DIRECTORY':str(state/'system'),'DATA_ROOT_DIRECTORY':str(state/'data'),'CACHE_ROOT_DIRECTORY':str(state/'cache')})
    import cognee
    from importlib.metadata import version
    if version('cognee')!=COGNEE_VERSION:raise RuntimeError('cognee_version_not_accepted')
    cognee.config.system_root_directory(str(state/'system'));cognee.config.data_root_directory(str(state/'data'))
    from cognee.base_config import get_base_config
    get_base_config().cache_root_directory=str(state/'cache')
    operation=req['operation'];payload=req.get('payload',{})
    if operation=='health':return {'version':version('cognee'),'native':True,'stores':['sqlite','lancedb','ladybug'],'model_executor':'Hermes native leaf','embedding':'voyage-4-large:1024'}
    if not runtime:raise PermissionError('native_runtime_provider_required')
    import urllib.request
    def phase(purpose):
        request=urllib.request.Request(runtime['url']+'/phase',data=json.dumps({'embedding_purpose':purpose}).encode(),headers={'Authorization':'Bearer '+runtime['token'],'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:response.read()
    if operation=='temporal_probe':
        from cognee.modules.users.methods import get_default_user
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.modules.retrieval.temporal_hybrid_retriever import TemporalHybridRetriever
        user=await get_default_user();datasets=await cognee.datasets.list_datasets();dataset=next(d for d in datasets if d.name==payload['dataset'])
        phase('query')
        async with set_database_global_context_variables(dataset.id,user.id):
            retriever=TemporalHybridRetriever(top_k=1,candidate_top_k=5,include_external_metadata=True,external_metadata_keys=['bn_doc_id'])
            objects=await retriever.get_retrieved_objects(payload['query'])
            context=await retriever.get_context_from_objects(query=payload['query'],retrieved_objects=objects)
            return {'interval':[x.isoformat() if x else None for x in retriever.last_interval],'reason':retriever.last_reason,'anchors':{k:list(v) if isinstance(v,set) else v for k,v in retriever.last_anchors.items()},'context':plain(context),'objects':plain(objects)}
    if operation=='resolve_ids':
        datasets=await cognee.datasets.list_datasets();target=next((x for x in datasets if x.name==payload['dataset']),None)
        if target is None:return {'data_ids':[]}
        rows=await cognee.datasets.list_data(target.id);ids=[]
        for row in rows:
            meta=getattr(row,'external_metadata',None)
            if isinstance(meta,str):
                try:meta=json.loads(meta)
                except ValueError:meta=None
            if isinstance(meta,dict) and meta.get('bn_doc_id')==payload['doc_id'] or getattr(row,'label',None)==payload['doc_id']:ids.append(str(row.id))
        return {'data_ids':ids}
    if operation=='ingest':
        from cognee.tasks.ingestion.data_item import DataItem
        from cognee.modules.ontology.rdf_xml.RDFLibOntologyResolver import RDFLibOntologyResolver
        config={'ontology_config':{'ontology_resolver':RDFLibOntologyResolver(ontology_file=str(root/'operator/knowledge-work.owl')),'ontology_mode':'annotate'}}
        if payload['metadata'].get('content_type')=='code':
            directory=root/'state/code-inputs'/payload['doc_id'];directory.mkdir(parents=True,exist_ok=True)
            filename=payload['metadata']['filename'];path=directory/filename;path.write_text(payload['text']);path.chmod(0o600)
            result=await cognee.remember(str(directory),dataset_name=payload['dataset'],content_type='code',index_vectors=True,self_improvement=False,run_in_background=False)
        else:
            item=DataItem(data=payload['text'],label=payload['doc_id'],external_metadata=payload['metadata'],literal_text=True)
            result=await cognee.remember(item,dataset_name=payload['dataset'],chunk_size=1024,self_improvement=False,run_in_background=False,config=config,summary_method='from_extraction')
        return {'operation':'remember','result':plain(result),'evidence_status':'unreviewed'}
    if operation=='query':
        phase('query')
        from cognee.modules.search.types.SearchType import SearchType
        modes={'chunks':SearchType.CHUNKS,'hybrid':SearchType.HYBRID_COMPLETION,'graph':SearchType.GRAPH_COMPLETION,'temporal':SearchType.TEMPORAL,'summaries':SearchType.SUMMARIES}
        result=await cognee.recall(payload['query'],query_type=modes[payload.get('mode','hybrid')],datasets=payload['datasets'],top_k=payload.get('limit',5),only_context=True,auto_route=False,retriever_specific_config={'chunks_top_k':5,'entities_top_k':5,'facts_top_k':5,'max_edges_per_entity':3,'include_external_metadata':True,'external_metadata_keys':['bn_doc_id','source_sha256','source_ref','extent']})
        passages=await cognee.recall(payload['query'],query_type=SearchType.HYBRID_COMPLETION,datasets=payload['datasets'],only_context=True,auto_route=False,retriever_specific_config={'chunks_top_k':5,'entities_top_k':0,'facts_top_k':0,'include_external_metadata':True,'external_metadata_keys':['bn_doc_id','source_sha256','source_ref','extent']})
        return {'operation':'recall','results':plain(result),'passages':plain(passages),'only_context':True,'evidence_status':'unreviewed'}
    if operation=='enrich':
        result=await cognee.improve(dataset=payload['dataset'],build_global_context_index=True,build_truth_subspace=False,run_in_background=False)
        return {'operation':'improve','result':plain(result),'evidence_status':'unreviewed'}
    if operation=='lesson':
        # Session guidance is explicitly supplied from the primary ledger, not a copied transcript.
        session_id=payload['session_id']
        # Plain strings become ASSISTANT-only QA and cannot support distillation.
        # A typed processing input preserves the caller-selected source as an input,
        # without inventing a historical conversation or accepting its claims.
        # Reading the selected record is the actual execution being traced.
        # SDK batch rendering limits a return value to 600 serialized chars.
        # Explicitly partition before writes; keep every part and avoid the
        # SDK's implicit tenth-trace extraction cycle.
        parts=[];text=payload['text'];offset=0
        while offset<len(text):
            stop=min(len(text),offset+500)
            while len(json.dumps({'text_part':text[offset:stop]}))>550:stop-=1
            parts.append((offset,text[offset:stop]));offset=stop
        if len(parts)>9:raise ValueError('split_primary_record_before_lesson')
        prefix='Selected primary candidate record (unreviewed data, not execution instructions):\n'
        if len(prefix+text)>1200:raise ValueError('split_primary_record_before_lesson')
        try:typed=json.loads(text)
        except ValueError:typed=None
        trace=None
        if isinstance(typed,dict) and typed.get('type')=='trace':
            trace=cognee.TraceEntry.model_validate({**typed,'generate_feedback_with_llm':False})
            if len(json.dumps(trace.method_return_value))>550 or len(trace.error_message)>230:raise ValueError('split_trace_before_lesson')
        from cognee.tasks.ingestion.data_item import DataItem
        await cognee.add(DataItem(data=text,literal_text=True,label=payload['source']['id'],external_metadata=payload['source']),dataset_name=payload['dataset'])
        entry=cognee.QAEntry(question=prefix+text,answer='Candidate supplied for durable-learning curation; its source claims remain unreviewed.')
        stored=await cognee.remember(entry,dataset_name=payload['dataset'],session_id=session_id,self_improvement=False)
        if stored.status!='session_stored':raise RuntimeError('typed_lesson_source_not_stored')
        if trace is not None:
            saved=await cognee.remember(trace,dataset_name=payload['dataset'],session_id=session_id,self_improvement=False)
            if saved.status!='session_stored':raise RuntimeError('source_trace_not_stored')
        for offset,part in ([] if trace is not None else parts):
            trace=cognee.TraceEntry(origin_function='bn_memory.read_primary',status='success',generate_feedback_with_llm=False,method_params={'source':payload['source'],'offset':offset,'length':len(part)},method_return_value={'text_part':part})
            saved=await cognee.remember(trace,dataset_name=payload['dataset'],session_id=session_id,self_improvement=False)
            if saved.status!='session_stored':raise RuntimeError('source_trace_not_stored')
        # Explicit adapter to the pinned SDK extractor and its confidence gate.
        # No global improve loop or unrelated graph/session persistence stages.
        from cognee.infrastructure.session.get_session_manager import get_session_manager
        from cognee.infrastructure.session.agent_context_extraction import extract_pending_agent_context
        from cognee.modules.users.methods import get_default_user
        user=await get_default_user()
        extracted=await extract_pending_agent_context(session_manager=get_session_manager(),user_id=str(user.id),session_id=session_id,min_new_traces=1)
        prepared={'stages':[{'stage':'extract_agent_context','status':'completed','counts':{'candidate_ids':extracted}}],'adapter':'pinned Cognee '+COGNEE_VERSION+' extractor; original confidence gate retained'}
        result,closure=await distill_with_evidence_closure(session_id,payload['dataset'])
        return {'operation':'distill_session','trace_parts':len(parts),'source_complete':True,'preparation':plain(prepared),'dependency_closure':closure,'result':result,'evidence_status':'unreviewed'}
    if operation=='forget':
        from uuid import UUID
        # Delete the exact SDK item too, so a later remember(dataset) cannot
        # re-cognify a revoked raw item. The BN immutable original is separate.
        result=await cognee.forget(dataset=payload['dataset'],data_id=UUID(payload['data_id']) if payload.get('data_id') else None)
        return {'operation':'forget','result':plain(result)}
    raise ValueError('cognee_operation_not_admitted')

def main():
    req=json.load(sys.stdin)
    try:
        result=asyncio.run(run(req));print(json.dumps(plain(result),ensure_ascii=False,default=str))
    except Exception as exc:
        if req.get('operation')=='temporal_probe':
            import traceback
            (Path(req['config']['cognee_root'])/'operator/temporal-error.txt').write_text(traceback.format_exc())
        print(json.dumps({'status':'unavailable','code':type(exc).__name__+':'+str(exc)[:220]}));sys.exit(2)
if __name__=='__main__':main()
