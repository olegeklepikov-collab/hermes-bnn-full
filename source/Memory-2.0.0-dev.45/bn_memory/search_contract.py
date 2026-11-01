"""Addressed and typed search over existing primary/lexical/vector stores; no agent recursion."""
import json,re,time
from bn_memory.store import canonical,sha,SENSITIVE

EXACT=re.compile(r'^(?:MEM-[a-f0-9]{24}|SRC-[a-f0-9]{32})$')

def read(broker,sid,identifier,revision=None):
    return broker.sources().read(sid,identifier,revision) if identifier.startswith('SRC-') else broker.store.read(sid,identifier,revision)

def addressed(broker,sid,versions,offset,limit):
    records=[];fragments=[];missing=[]
    if not 1<=len(versions)<=256:raise ValueError('split_version_map_without_trimming')
    if len({v['id'] for v in versions})!=len(versions):raise ValueError('duplicate_version_map_id')
    if any(set(v)!={'id','revision','content_hash'} or not EXACT.fullmatch(v['id']) or type(v['revision']) is not int or v['revision']<1 or not re.fullmatch('[a-f0-9]{64}',v['content_hash']) for v in versions):raise ValueError('version_map_invalid')
    for v in versions[offset:offset+limit]:
        if not EXACT.fullmatch(v['id']) or type(v['revision']) is not int or v['revision']<1:raise ValueError('version_map_invalid')
        try:
            row=read(broker,sid,v['id'],v['revision'])
            if row['content_hash']!=v['content_hash']:raise PermissionError('expected_primary_version_mismatch')
            (fragments if v['id'].startswith('SRC-') else records).append(row)
        except (PermissionError,KeyError,ValueError,FileNotFoundError) as exc:
            missing.append({'id':v['id'],'revision':v['revision'],'status':'unavailable_or_changed','code':type(exc).__name__})
    return {'records':records,'source_fragments':fragments,'unavailable':missing,'has_more':offset+limit<len(versions),
        'next_offset':offset+limit if offset+limit<len(versions) else None,'assigned_version_count':len(versions),
        'version_map_sha256':sha(canonical(versions)),'retrieval_completeness':'assigned_version_map_only','evidence_status':'unreviewed','remote_calls':0}

def execute(broker,sid,args,ranked):
    result=_execute(broker,sid,args,ranked)
    result.setdefault('ranked_results',[{'id':r['id'],'kind':'source' if r['id'].startswith('SRC-') else 'memory','fusion_score':None}
        for r in result['records']+result.get('source_fragments',[])])
    result.setdefault('derived',{});result.setdefault('scope',broker.store.scopes(broker.store.binding(sid)))
    return result

def _execute(broker,sid,args,ranked):
    store=broker.store;binding=store.binding(sid);query=args['query'];strategy=args.get('strategy','semantic' if args.get('mode')=='hybrid' else 'lexical')
    offset=args.get('offset',0);limit=args.get('limit',5)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=10:raise ValueError('page_invalid')
    if not isinstance(query,str):raise ValueError('search_query_must_be_text')
    if SENSITIVE.search(canonical(args)):raise PermissionError('secret_not_search_input')
    need=args.get('need')
    if need is not None:
        if set(need)!={'purpose','expected_output','sufficiency','scope'} or need['scope']!='current_authorized_scopes' or any(not isinstance(need[k],str) or not need[k].strip() for k in need):raise ValueError('complete_search_need_required')
    if 'strategy' in args and need is None:raise ValueError('typed_search_requires_need')
    contract={'strategy':strategy,'need':need,'actual_scope':store.scopes(binding),'current_project':binding['project'],
              'sufficiency':'caller must evaluate evidence; a top-k result is not full coverage','evidence_status':'unreviewed'}
    if strategy=='snapshot':
        if 'versions' not in args:raise ValueError('explicit_version_map_required')
        return {**addressed(broker,sid,args['versions'],offset,limit),'search_contract':contract}
    if 'versions' in args:raise ValueError('version_map_requires_snapshot_strategy')
    if 'example' in args and strategy!='example':raise ValueError('example_requires_example_strategy')
    # Known exact IDs are read before embedding/provider routing, including legacy
    # calls that supplied only query/mode. A miss never becomes broad web search.
    if EXACT.fullmatch(query.strip()):
        identifier=query.strip()
        try:
            row=read(broker,sid,identifier);result={'records':[row] if identifier.startswith('MEM-') else [],'source_fragments':[row] if identifier.startswith('SRC-') else [],'unavailable':[]}
        except (PermissionError,KeyError,ValueError,FileNotFoundError):result={'records':[],'source_fragments':[],'unavailable':[{'id':identifier,'status':'unavailable_in_current_scope'}]}
        return {**result,'search_contract':{**contract,'strategy':'exact'},'has_more':False,'remote_calls':0,'retrieval_completeness':'one_exact_identifier'}
    if strategy=='exact':raise ValueError('exact_primary_identifier_required')
    if strategy=='example':
        example=args.get('example')
        if not isinstance(example,dict) or set(example)!={'object','goal','environment','features','unknowns'}:raise ValueError('complete_search_example_required')
        if any(not isinstance(example[k],str) or not example[k].strip() for k in ['object','goal','environment']):raise ValueError('example_object_goal_environment_required')
        if not isinstance(example['features'],list) or not example['features'] or not isinstance(example['unknowns'],list):raise ValueError('example_features_unknowns_required')
        query='\n'.join([query,example['object'],example['goal'],example['environment'],*example['features']])
        contract.update(example=example,effective_query=query,differences='Not inferred by retrieval. Verify differences against primary cases before applying an analogy.')
    elif 'example' in args:raise ValueError('example_requires_example_strategy')
    if not query.strip():return {'records':[],'source_fragments':[],'has_more':False,'remote_calls':0,'stop_reason':'empty_need_no_collection','search_contract':contract}
    if strategy not in {'semantic','lexical','targeted','example','heuristic'}:raise ValueError('search_strategy_invalid')
    trace=args.get('trace_id');reason=args.get('step_reason')
    if strategy=='heuristic' and (not isinstance(trace,str) or not trace.strip() or not isinstance(reason,str) or not reason.strip()):raise ValueError('heuristic_trace_and_reason_required')
    mode='local' if strategy=='lexical' else args.get('mode','hybrid')
    scoped={'query':query,'mode':mode,'limit':limit,'offset':offset}
    if strategy!='heuristic':
        result={**ranked(broker,sid,scoped),'search_contract':contract}
        if mode=='local':result['remote_calls']=0
        return result
    # A different arbitrary trace ID does not make an identical attempt novel.
    # Primary/permission changes do; pagination is a distinct addressed step.
    basis=store.retrieval_basis(sid);key=sha(canonical([store.profile,sid,basis,scoped]))
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS search_steps(profile_id TEXT,sid TEXT,id TEXT,trace_id TEXT,basis TEXT,state TEXT,body TEXT,PRIMARY KEY(profile_id,sid,id))')
        db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT state,body FROM search_steps WHERE profile_id=? AND sid=? AND id=?',(store.profile,sid,key)).fetchone()
        if old:
            data=json.loads(old[1]);return {'records':[],'source_fragments':[],'has_more':False,'remote_calls':0,'stop_reason':'no_new_input_or_progress',
                'previous_step_state':old[0],'previous_result_refs':data.get('result_refs',[]),'search_contract':contract,'basis':basis,'trace_id':trace}
        db.execute('INSERT INTO search_steps VALUES(?,?,?,?,?,?,?)',(store.profile,sid,key,trace,basis,'started',canonical({'query':query,'reason':reason,'created':time.time()})))
    try:
        result=ranked(broker,sid,scoped)
        if mode=='local':result['remote_calls']=0
        if store.retrieval_basis(sid)!=basis:raise PermissionError('search_primary_basis_changed_retry_with_current_input')
        refs=[{'id':r['id'],'revision':r.get('revision',1),'content_hash':r['content_hash']} for r in result['records']+result.get('source_fragments',[])]
        with store.db() as db:db.execute("UPDATE search_steps SET state='completed',body=? WHERE profile_id=? AND sid=? AND id=?",(canonical({'query':query,'reason':reason,'result_refs':refs}),store.profile,sid,key))
        return {**result,'search_contract':contract,'basis':basis,'trace_id':trace,'step_reason':reason,'novelty':'new query/page or changed primary/permission basis'}
    except BaseException:
        with store.db() as db:db.execute("UPDATE search_steps SET state='failed_requires_new_basis',body=? WHERE profile_id=? AND sid=? AND id=?",(canonical({'query':query,'reason':reason}),store.profile,sid,key))
        raise
