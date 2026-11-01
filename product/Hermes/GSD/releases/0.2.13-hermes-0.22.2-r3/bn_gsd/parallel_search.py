"""Fixed read-only fan-out through native controlled executors, not arbitrary code."""
import contextvars,json,threading,uuid
from concurrent.futures import ThreadPoolExecutor,as_completed
SCHEMA={'name':'bn_parallel_search','description':'Параллельный сбор независимых поисковых запросов через штатный web_search. Каждый запрос проходит обязательный контроль и защиту от повторов. Не запускает дочерних агентов и G/S/D; не выполняет код и не записывает файлы. Новые источники и их чтение оценивай по фактическим ответам.',
 'parameters':{'type':'object','additionalProperties':False,'properties':{'queries':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','minLength':1,'maxLength':4096}},'limit':{'type':'integer','minimum':1,'maximum':100,'default':5}},'required':['queries']}}
def validate(args):
 if not isinstance(args,dict) or set(args)-{'queries','limit'}:raise ValueError('Only independent queries and result limit are admitted')
 queries=args.get('queries');limit=args.get('limit',5)
 if not isinstance(queries,list) or not 1<=len(queries)<=8 or any(not isinstance(q,str) or not q.strip() or len(q)>4096 for q in queries):raise ValueError('Split work into independent batches of 1–8 nonempty queries')
 if len(set(queries))!=len(queries):raise ValueError('Duplicate queries in one batch are not independent work')
 if type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid native search result limit')
 return queries,limit
class ParallelSearch:
 def __init__(self,runtime):self.runtime=runtime;self.guard_lock=threading.RLock()
 def run(self,args,session_id='',turn_id='',tool_call_id='',**kw):
  queries,limit=validate(args)
  from agent.subagent_lifecycle import get_active_subagent_parent
  from hermes_cli.middleware import run_tool_execution_middleware
  from hermes_cli.plugins import invoke_hook
  from tools.registry import registry
  parent=get_active_subagent_parent();state=self.runtime.bridge.call('lookup',{'sid':session_id})
  if parent is None or parent.session_id!=session_id or state['session'].get('parent') or state.get('job') or getattr(parent,'platform','')=='subagent':raise ValueError('A live native root and inherited policy are required')
  if state['family']['status']!='running':raise ValueError('The parent family is stopped')
  guard=getattr(parent,'_tool_guardrails',None)
  if guard is None:raise ValueError('Required native repeat controller is unavailable')
  base=tool_call_id or 'parallel-'+uuid.uuid4().hex
  results=[None]*len(queries)
  def collect(index):
   query=queries[index];params={'query':query,'limit':limit};cid=base+'.search-'+str(index)
   identity={'session_id':session_id,'turn_id':turn_id,'tool_call_id':cid,'platform':parent.platform,'parent_agent':parent}
   if getattr(parent,'_interrupt_requested',False):return {'index':index,'query':query,'status':'cancelled','source_call_started':False}
   with self.guard_lock:decision=guard.before_call('web_search',params)
   if not decision.allows_execution:
    parent._set_tool_guardrail_halt(decision)
    return {'index':index,'query':query,'status':'blocked','source_call_started':False,'guardrail':decision.to_metadata()}
   invoke_hook('pre_tool_call',tool_name='web_search',args=params,**identity)
   try:
    def native_search(clean):
     if getattr(parent,'_interrupt_requested',False):raise InterruptedError('Parent stopped before source execution')
     return registry.dispatch('web_search',clean,**identity)
    result=run_tool_execution_middleware('web_search',params,native_search,**identity)
    if getattr(parent,'_interrupt_requested',False):raise InterruptedError('Parent stopped; completed source result is not released')
    from agent.tool_guardrails import classify_tool_failure
    failed,_=classify_tool_failure('web_search',result)
    with self.guard_lock:after=guard.after_call('web_search',params,result,failed=failed)
    if after.should_halt:parent._set_tool_guardrail_halt(after)
    row={'index':index,'query':query,'status':'failed' if failed else 'returned','source_result':result,'reading_level':'search_result_only','guardrail':after.to_metadata()}
   except Exception as exc:
    result='Error '+str(exc)
    with self.guard_lock:after=guard.after_call('web_search',params,result,failed=True)
    if after.should_halt:parent._set_tool_guardrail_halt(after)
    row={'index':index,'query':query,'status':'blocked_or_failed','error_type':type(exc).__name__,'error':str(exc),'guardrail':after.to_metadata()}
   invoke_hook('post_tool_call',tool_name='web_search',args=params,result=result,status='error' if row['status']!='returned' else 'ok',**identity)
   return row
  # Context is copied separately: credentials, profile and parent authority stay scoped.
  with ThreadPoolExecutor(max_workers=min(4,len(queries)),thread_name_prefix='bn-search') as pool:
   futures={pool.submit(contextvars.copy_context().run,collect,i):i for i in range(len(queries))}
   for future in as_completed(futures):results[futures[future]]=future.result()
  return {'ok':all(r['status']=='returned' for r in results),'execution':'native_controlled_parallel_search','results':results,'result_count':len(results),'max_workers':min(4,len(queries)),'new_agents':0,'arbitrary_code_executed':False,'scientific_acceptance':False}
