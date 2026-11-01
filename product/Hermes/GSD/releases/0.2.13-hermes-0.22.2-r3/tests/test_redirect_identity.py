from test_host_contracts import host
from test_response_recovery import runtime_stub
from bn_gsd.runtime import Runtime
from bn_gsd.bridge import Bridge
from types import SimpleNamespace

def test_redirect_with_reused_native_id_is_distinct_and_same_payload_cannot_replay(host,monkeypatch):
    host.settings['limits'].update(budget_mode='observe',tokens=None,model_calls=None,wall_seconds=None,child_jobs=None,tool_calls=None,role_model_calls=None)
    import json
    host.path.write_text(json.dumps(host.settings));host('operator_observation_mode',{'reason':'Synthetic owner choice'})
    monkeypatch.setenv('HERMES_HOME',str(host.path.parent.parent))
    r=runtime_stub();r.bound_state=lambda *a:host('lookup',{'sid':'root'});r.bridge=Bridge(host.path)
    base={'model':'gpt-6.1-sol','input':[{'role':'user','content':'original'}],'max_output_tokens':4096}
    corrected={**base,'input':base['input']+[{'role':'user','content':'native user correction'}]}
    def allow(req):return r.model_control('llm',{'request':req},session_id='root',api_request_id='same-iteration',provider='openai-codex')
    first=allow(base);assert first.allow
    def interrupted(req):raise InterruptedError('user redirect')
    import pytest
    with pytest.raises(InterruptedError):r.model_execution(base,interrupted,api_request_id='same-iteration')
    state=host('family_status',{'sid':'root'})['resource'];spent=state['spent_tokens'];assert spent>0 and state['reserved_tokens']==0
    assert not allow(base).allow
    second=allow(corrected);assert second.allow and second.reservation_id!=first.reservation_id
    assert not allow({**corrected,'input':[]}).allow  # unsettled predecessor still closes path
    r.model_execution(corrected,lambda req:{'usage':{'total_tokens':10}},api_request_id='same-iteration')
    state=host('family_status',{'sid':'root'})['resource'];assert state['spent_tokens']==spent+10 and state['reserved_tokens']==0
    assert not allow(corrected).allow and not allow(base).allow
    r.post_api(api_request_id='same-iteration',usage={'total_tokens':999})
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==spent+10
