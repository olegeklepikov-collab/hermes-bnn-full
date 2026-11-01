"""Actual signed accounting; synthetic executor failures, never model success."""
import pytest
from types import SimpleNamespace
from test_host_contracts import host
from bn_gsd.runtime import Runtime


def runtime(host):
    value=Runtime.__new__(Runtime)
    value.bridge=SimpleNamespace(call=lambda op,args:host(op,args))
    return value


def test_interruption_keeps_unknown_cost_and_unblocks_next_attempt(host):
    r=runtime(host)
    host('reserve',{'sid':'root','request_id':Runtime.physical_request_id('cancelled',{}),'fingerprint':'f','upper_tokens':100})
    calls=[]
    def interrupted(request):
        calls.append(request)
        raise InterruptedError('synthetic cancellation')
    with pytest.raises(InterruptedError):r.model_execution({},interrupted,api_request_id='cancelled')
    state=host('family_status',{'sid':'root'})['resource']
    assert len(calls)==1 and state['reserved_tokens']==0 and state['spent_tokens']==100 and state['unknown_usage_reservations']==1
    assert state['unsettled_provider_attempts']==0 and state['unknown_usage_accounted_attempts']==1
    host('reserve',{'sid':'root','request_id':'next','fingerprint':'f','upper_tokens':100})
    host('settle',{'request_id':'next','actual_tokens':10})
    host('reserve',{'sid':'root','request_id':Runtime.physical_request_id('cancelled',{}),'fingerprint':'f','upper_tokens':100},ok=False)
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==110


def test_wrapped_downstream_failure_is_propagated_without_replay(host):
    from hermes_cli.middleware import _DownstreamExecutionError
    r=runtime(host)
    host('reserve',{'sid':'root','request_id':Runtime.physical_request_id('wrapped',{}),'fingerprint':'f','upper_tokens':100})
    def interrupted(request):raise _DownstreamExecutionError(InterruptedError('synthetic nested cancellation'))
    with pytest.raises(_DownstreamExecutionError):r.model_execution({},interrupted,api_request_id='wrapped')
    assert host('family_status',{'sid':'root'})['resource']['reserved_tokens']==0
    # Repeated observer notification neither refunds nor counts a second charge.
    host('settle',{'request_id':Runtime.physical_request_id('wrapped',{}),'error':True})
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==100


def test_success_retains_observed_usage_and_other_live_attempt_is_protected(host):
    r=runtime(host)
    host('reserve',{'sid':'root','request_id':Runtime.physical_request_id('success',{}),'fingerprint':'f','upper_tokens':100})
    response={'synthetic_contract_fixture':True,'usage':{'total_tokens':10}}
    assert r.model_execution({},lambda _:response,api_request_id='success') is response
    assert host('family_status',{'sid':'root'})['resource']['reserved_tokens']==0
    r.post_api(api_request_id='success',usage={'total_tokens':10})
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==10
    # An attempt that was never authorized cannot close another pending request.
    host('reserve',{'sid':'root','request_id':'live','fingerprint':'f','upper_tokens':100})
    with pytest.raises(InterruptedError):r.model_execution({},lambda _:(_ for _ in ()).throw(InterruptedError()),api_request_id='different')
    assert host('family_status',{'sid':'root'})['resource']['reserved_tokens']==100


def test_received_response_with_unavailable_usage_is_closed_conservatively(host):
    r=runtime(host)
    host('reserve',{'sid':'root','request_id':Runtime.physical_request_id('discarded',{}),'fingerprint':'f','upper_tokens':100})
    value=object()
    assert r.model_execution({},lambda _:value,api_request_id='discarded') is value
    state=host('family_status',{'sid':'root'})['resource']
    assert state['unsettled_provider_attempts']==0 and state['reserved_tokens']==0
    assert state['unknown_usage_accounted_attempts']==1 and state['spent_tokens']==100
