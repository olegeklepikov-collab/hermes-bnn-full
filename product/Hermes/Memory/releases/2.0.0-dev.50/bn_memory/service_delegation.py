"""Exact service and parameter attenuation for UDR, ordinary teams and G/S/D."""
from bn_memory.service_engine import validate_call
from bn_memory.store import canonical,sha
def permissions(config,calls):
 if not isinstance(calls,(list,tuple)) or len(calls)>64:raise ValueError('split_assigned_service_calls_required')
 out=[];seen=set()
 for call in calls:
  if not isinstance(call,dict) or set(call)-{'service','method','arguments','input_files'} or not {'service','method','arguments'}<=set(call):raise ValueError('assigned_service_call_contract_invalid')
  validate_call(config,'read',call)
  rule='services.'+call['service']+'.'+call['method']
  branch={'type':'object','properties':{'service':{'const':call['service']},'method':{'const':call['method']},'arguments':{'const':call['arguments']},'input_files':{'const':call.get('input_files',[])}},'required':['service','method','arguments']+(['input_files'] if call.get('input_files') else [])}
  # Keep whole argument/file pairs; a Cartesian union would widen delegation.
  if rule in seen:
   item=next(x for x in out if x['rule_id']==rule);values=item['arguments_schema']['anyOf']
   if branch not in values:values.append(branch)
  else:
   seen.add(rule);out.append({'rule_id':rule,'arguments_schema':{'anyOf':[branch]}})
 if calls:out.extend({'rule_id':n,'arguments_schema':{'type':'object'}} for n in ['services.service_catalog','services.service_result','services.skills'])
 return out

def close_resources(host,sid,resources,calls):
 import copy
 out=copy.deepcopy(resources or {})
 for call in calls:
  for name in call.get('input_files',[]):
   _,path=host.store.safe_file(sid,name)
   if str(path) not in out.setdefault('files',[]):out['files'].append(str(path))
 return out
