from test_host_contracts import host
from bn_gsd.runtime import Runtime
from types import SimpleNamespace

def test_operator_window_preserves_costs_and_replay_denial(host):
    host('operator_output_limit',{'sid':'root','maximum':4096,'reason':'Synthetic smaller window'})
    host('reserve',{'sid':'root','request_id':'spent','fingerprint':'f','upper_tokens':100})
    host('settle',{'request_id':'spent','actual_tokens':40})
    before=host('family_status',{'sid':'root'})['resource']
    host('operator_output_limit',{'sid':'root','maximum':32768,'reason':'Synthetic reasoning headroom'})
    after=host('family_status',{'sid':'root'})['resource']
    for key in ['spent_tokens','reserved_tokens','authorized_calls','jobs_started','deadline','unknown_usage_reservations']:assert before[key]==after[key]
    assert after['limits']['output_tokens']==32768
    host('reserve',{'sid':'root','request_id':'spent','fingerprint':'f','upper_tokens':100},ok=False)
    host('reserve',{'sid':'root','request_id':'pending','fingerprint':'f','upper_tokens':10})
    host('operator_output_limit',{'sid':'root','maximum':4096,'reason':'Must not change unresolved attempt'},ok=False)

def runtime_stub():
    r=Runtime.__new__(Runtime);r.settings={'provider':'openai-codex','limits':{'output_tokens':32768,'request_bytes':2097152}}
    r.bound_state=lambda *a:{'family':{'limits':{'output_tokens':4096,'request_bytes':2097152}},'job':None}
    return r

def test_captured_family_output_constraint_is_preserved():
    r=runtime_stub();changed=r.request_middleware({'input':[],'max_output_tokens':32768},session_id='synthetic')['request']
    assert changed['max_output_tokens']==4096

def test_expected_reservation_denial_is_explicit():
    r=runtime_stub()
    def deny(*args):raise ValueError('Physical provider request was already reserved; automatic repetition is forbidden')
    r.bridge=SimpleNamespace(call=deny)
    decision=r.model_control('llm',{'request':{'model':'gpt-6.1-sol','input':[],'max_output_tokens':4096}},session_id='synthetic',api_request_id='spent',provider='openai-codex')
    assert not decision.allow and 'already reserved' in decision.reason

def test_observation_mode_crosses_old_caps_without_losing_accounting(host):
    import json
    host('reserve',{'sid':'root','request_id':'known','fingerprint':'f','upper_tokens':100})
    host('settle',{'request_id':'known','actual_tokens':40})
    before=host('family_status',{'sid':'root'})['resource']
    host.settings['limits']['budget_mode']='observe'
    host.path.write_text(json.dumps(host.settings))
    host('operator_observation_mode',{'reason':'Explicit synthetic owner instruction'})
    current=host('family_status',{'sid':'root'})['resource']
    assert current['spent_tokens']==40 and current['deadline'] is None
    assert all(current['limits'][k] is None for k in ['tokens','model_calls','child_jobs','wall_seconds','tool_calls','role_model_calls'])
    host('reserve',{'sid':'root','request_id':'over-old-cap','fingerprint':'f','upper_tokens':10000})
    host('reserve',{'sid':'root','request_id':'over-old-cap','fingerprint':'f','upper_tokens':10000},ok=False)
    host('settle',{'request_id':'over-old-cap','error':True})
    for n in range(6):host('tool_call',{'sid':'root','name':'synthetic-'+str(n)})
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==10040
