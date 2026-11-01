from test_host_contracts import host
import time, pytest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_exact_tool_grant_is_shared_scoped_revocable_and_non_replayable(host):
    args={'sid':'root','name':'mcp__example__publish','arguments':{'text':'synthetic'},'ttl':300,'reason':'Synthetic test'}
    grant=host('issue_tool_grant',args)
    from bn_gsd.codec import digest
    request={'sid':'root','name':args['name'],'args_digest':digest(args['arguments']),'call_id':'call1','boundary':'execution_middleware'}
    host('authorize_tool_grant',{**request,'args_digest':'0'*64},ok=False)
    host('authorize_tool_grant',request)
    host('authorize_tool_grant',{**request,'boundary':'registry'})
    host('authorize_tool_grant',request,ok=False)
    host('evidence_event',{'sid':'root','event':{'tool_call_id':'call1','result_sha256':'synthetic'}})
    host('authorize_tool_grant',{**request,'call_id':'call2'},ok=False)
    other=host('issue_tool_grant',{**args,'arguments':{'text':'other'}})
    host('revoke_grant',{'grant_id':other['grant_id'],'reason':'Revoked'})
    host('authorize_tool_grant',{**request,'args_digest':digest({'text':'other'}),'call_id':'call3'},ok=False)


def test_migration_inspection_uses_real_source_without_reset(host,tmp_path):
    before=host('family_status',{'sid':'root'})['resource']
    plan=host('operator_migrate',{'backup_path':str(tmp_path/'migration.sqlite'),'apply':False})
    assert plan['runs']==[] and plan['counter_reset'] is False
    after=host('family_status',{'sid':'root'})['resource']
    assert before==after


def test_missing_external_executor_never_commits(host):
    host('operator_external_commit',{'job_id':'absent','run_id':'absent','payload':{},'request_id':'x','review_reason':'Synthetic'},ok=False)


def test_restored_root_binding_is_idempotent_and_unknown_child_stays_closed(host):
    from bn_gsd.runtime import Runtime
    r=Runtime.__new__(Runtime)
    class Bridge:
        def call(self,operation,args):return host(operation,args)
    # Use the real worker but preserve production exception semantics.
    class StrictBridge:
        def call(self,operation,args):
            try:return host(operation,args)
            except AssertionError:
                raise ValueError('Native lifecycle did not bind this session')
    r.bridge=StrictBridge()
    state=r.bound_state('restored-old-telegram','telegram')
    host('reserve',{'sid':'restored-old-telegram','request_id':'restored-call','fingerprint':'f','upper_tokens':100})
    host('settle',{'request_id':'restored-call','actual_tokens':40})
    assert r.bound_state('restored-old-telegram','telegram')['family']['spent_tokens']==40
    assert r.bound_state('restored-old-telegram','telegram')['session']==state['session']
    with pytest.raises(ValueError):r.bound_state('orphan-child','subagent')


def test_dead_root_provider_is_charged_conservatively_then_requires_owner_resume(host):
    host('reserve',{'sid':'root','request_id':'lost','fingerprint':'f','upper_tokens':100,'owner':{'pid':999999999,'created_at':1.0}})
    recovered=host('recover_dead');assert recovered['recovered_unknown_requests']==['lost']
    state=host('family_status',{'sid':'root'});assert state['resource']['status']=='paused'
    assert state['resource']['reserved_tokens']==0 and state['resource']['spent_tokens']==100
    host('reserve',{'sid':'root','request_id':'blocked','fingerprint':'f','upper_tokens':10},ok=False)
    host('operator_resume',{'family_id':state['family_id'],'reason':'Observed synthetic process exit'})
    host('reserve',{'sid':'root','request_id':'next','fingerprint':'f','upper_tokens':50})
    assert host('family_status',{'sid':'root'})['resource']['spent_tokens']==100


def test_multimedia_reservation_does_not_treat_a_short_url_as_a_short_input():
    from bn_gsd.runtime import Runtime
    request={'model':'gpt-6.1-sol','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.invalid/synthetic.png'}}]}]}
    assert Runtime.input_upper_bound(request,1000,4096)>=1050000+4096
    with pytest.raises(ValueError):Runtime.input_upper_bound({**request,'model':'unverified-model'},1000,4096)
    assert Runtime.input_upper_bound({'messages':[{'role':'user','content':'text'}]},1000,100)==9292
