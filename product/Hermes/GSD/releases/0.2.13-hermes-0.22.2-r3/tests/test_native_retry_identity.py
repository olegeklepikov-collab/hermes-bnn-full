"""Distinct native attempts retain their own cost and settle the final admitted payload."""
import pytest
from types import SimpleNamespace
from test_host_contracts import host
from test_response_recovery import runtime_stub
from bn_gsd.bridge import Bridge
from bn_gsd.runtime import Runtime
def prepared(host,monkeypatch):
 host.settings['limits'].update(budget_mode='observe',tokens=None,model_calls=None,wall_seconds=None,child_jobs=None,tool_calls=None,role_model_calls=None)
 import json
 host.path.write_text(json.dumps(host.settings));host('operator_observation_mode',{'reason':'Synthetic contract verification'});monkeypatch.setenv('HERMES_HOME',str(host.path.parent.parent));r=runtime_stub();r.bound_state=lambda *a:host('lookup',{'sid':'root'});r.bridge=Bridge(host.path);return r
def test_retry_is_distinct_but_duplicate_attempt_stays_forbidden(host,monkeypatch):
 r=prepared(host,monkeypatch);request={'model':'gpt-6.1-sol','input':[{'role':'user','content':'same protected original'}],'max_output_tokens':4096};ids=[]
 def run(number,fail=False):
  def dispatch(value):
   d=r.model_control('llm',{'request':value},session_id='root',api_request_id='logical',provider='openai-codex',retry_count=number);assert d.allow;ids.append(d.reservation_id)
   if fail:raise InterruptedError('synthetic transport failure')
   return {'usage':{'total_tokens':10}}
  return r.model_execution(request,dispatch,api_request_id='logical',retry_count=number)
 with pytest.raises(InterruptedError):run(0,True)
 before=host('family_status',{'sid':'root'})['resource'];run(1);after=host('family_status',{'sid':'root'})['resource']
 assert ids[0]!=ids[1] and after['spent_tokens']==before['spent_tokens']+10 and after['reserved_tokens']==0 and after['unknown_usage_accounted_attempts']==1
 assert not r.model_control('llm',{'request':request},session_id='root',api_request_id='logical',provider='openai-codex',retry_count=1).allow
def test_final_admission_id_is_settled_after_request_rewrite(host,monkeypatch):
 r=prepared(host,monkeypatch);original={'model':'gpt-6.1-sol','input':[{'role':'user','content':'short caller'}],'max_output_tokens':4096};final={**original,'input':[{'role':'user','content':'full mandatory source appended by later middleware'}]}
 def dispatch(value):
  decision=r.model_control('llm',{'request':final},session_id='root',api_request_id='rewritten',provider='openai-codex');assert decision.allow
  return {'usage':{'total_tokens':17}}
 r.model_execution(original,dispatch,api_request_id='rewritten');state=host('family_status',{'sid':'root'})['resource'];assert state['reserved_tokens']==0 and state['spent_tokens']==17 and state['unsettled_provider_attempts']==0
