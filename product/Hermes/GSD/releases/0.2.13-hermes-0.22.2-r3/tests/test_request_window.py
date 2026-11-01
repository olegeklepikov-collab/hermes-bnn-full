from test_host_contracts import host
from test_response_recovery import runtime_stub
from types import SimpleNamespace

def test_request_adjustment_preserves_accounting_and_replay_guard(host):
    host.settings['limits']['request_bytes']=8388608
    import json
    host.path.write_text(json.dumps(host.settings))
    host('reserve',{'sid':'root','request_id':'done','fingerprint':'f','upper_tokens':100})
    host('settle',{'request_id':'done','actual_tokens':40})
    before=host('family_status',{'sid':'root'})['resource']
    result=host('operator_request_limit',{'sid':'root','maximum':8388608,'reason':'Keep mandatory context intact'})
    after=host('family_status',{'sid':'root'})['resource']
    assert result['shared_budget_reset'] is False and result['completed_jobs_replayed'] is False
    assert after['limits']['request_bytes']==8388608
    for key in ['spent_tokens','reserved_tokens','authorized_calls','jobs_started','deadline']:
        assert after[key]==before[key]
    host('reserve',{'sid':'root','request_id':'done','fingerprint':'f','upper_tokens':100},ok=False)
    for value,reason in [(8388609,'test'),(True,'test'),(8388608,'')]:
        host('operator_request_limit',{'sid':'root','maximum':value,'reason':reason},ok=False)
    host('reserve',{'sid':'root','request_id':'pending','fingerprint':'f','upper_tokens':10})
    host('operator_request_limit',{'sid':'root','maximum':2097152,'reason':'Must wait for settlement'},ok=False)

def test_serialized_limit_is_finite_and_does_not_trim_or_call_executor():
    r=runtime_stub();r.settings['limits']['request_bytes']=8388608
    cap={'value':2097152};calls=[]
    r.bound_state=lambda *a:{'family':{'limits':{'output_tokens':4096,'request_bytes':cap['value']}},'job':None}
    r.bridge=SimpleNamespace(call=lambda op,args:(calls.append((op,args)) or {'id':'admitted'}))
    request={'model':'gpt-6.1-sol','input':[{'role':'user','content':'Я'*1100000}],'max_output_tokens':4096}
    original=request['input'][0]['content']
    def decision():return r.model_control('llm',{'request':request},session_id='synthetic',api_request_id='a',provider='openai-codex')
    assert not decision().allow and calls==[]
    cap['value']=8388608
    assert decision().allow and len(calls)==1 and request['input'][0]['content']==original
    request['input'][0]['content']='Я'*4200000
    assert not decision().allow and len(calls)==1
