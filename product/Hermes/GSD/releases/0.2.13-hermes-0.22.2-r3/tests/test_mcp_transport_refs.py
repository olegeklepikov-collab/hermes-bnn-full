"""Native config loaders and secret scopes; no networking or secret values in evidence."""
from pathlib import Path
import hashlib,json
import pytest,yaml
from bn_gsd.tool_policy import ToolPolicy,transport_digest
from agent.secret_scope import set_secret_scope,reset_secret_scope
from tools import mcp_tool

@pytest.fixture
def policy(tmp_path,monkeypatch):
    home=tmp_path/'A';home.mkdir();monkeypatch.setenv('HERMES_HOME',str(home))
    raw={'url':'https://example.org/mcp','headers':{'Authorization':'Bearer ${TEST_MCP_KEY}'},'timeout':30,'enabled':True}
    (home/'config.yaml').write_text(yaml.safe_dump({'mcp_servers':{'search':raw}}))
    p=tmp_path/'policy.json';p.write_text(json.dumps({'version':1,'entries':{'mcp__search__find':{'server':'search','mode':'existing_owner_scope'}}}))
    settings={'tool_policy':str(p),'tool_policy_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mcp_transport_digests':{'search':transport_digest(raw)}}
    value=ToolPolicy(settings);mcp_tool._mcp_tool_server_names['mcp__search__find']='search'
    return value,home,raw

def scoped(value,home,key='synthetic-key'):
    token=set_secret_scope({'TEST_MCP_KEY':key},profile_home=str(home))
    try:return value.classify('mcp__search__find',{'query':'synthetic'})
    finally:reset_secret_scope(token)

def test_literal_admission_accepts_native_profile_expansion_and_rotation(policy):
    value,home,_=policy
    assert scoped(value,home)['server']=='search'
    assert scoped(value,home,'synthetic-rotated-key')['server']=='search'

@pytest.mark.parametrize('change',['url','command','headers','timeout'])
def test_source_transport_changes_are_denied(policy,change):
    value,home,raw=policy;new=dict(raw);new[change]={'url':'https://other.example/mcp','command':'unexpected','headers':{'Authorization':'Bearer ${OTHER_KEY}'},'timeout':31}[change]
    (home/'config.yaml').write_text(yaml.safe_dump({'mcp_servers':{'search':new}}))
    with pytest.raises(ValueError,match='source transport/config changed'):scoped(value,home)

def test_effective_overlay_provenance_and_unresolved_reference_are_denied(policy,monkeypatch):
    value,home,raw=policy
    token=set_secret_scope({},profile_home=str(home))
    try:
        with pytest.raises(ValueError,match='unresolved'):value.classify('mcp__search__find',{})
    finally:reset_secret_scope(token)
    from hermes_cli import managed_scope
    monkeypatch.setattr(managed_scope,'load_managed_config',lambda:{'mcp_servers':{'search':{'url':'https://other.example/mcp'}}})
    managed_scope.invalidate_managed_cache()
    with pytest.raises(ValueError,match='effective transport differs'):scoped(value,home)

def test_actual_provenance_and_profile_scope_are_required(policy,tmp_path):
    value,home,_=policy
    mcp_tool._mcp_tool_server_names['mcp__search__find']='other'
    with pytest.raises(ValueError,match='provenance'):scoped(value,home)
    other=tmp_path/'B';other.mkdir()
    with pytest.raises(ValueError,match='another profile'):scoped(value,other)

def test_expected_admission_refusal_is_explicit_not_generic_controller_failure():
    from types import SimpleNamespace
    from bn_gsd.runtime import Runtime
    r=Runtime.__new__(Runtime)
    r.bridge=SimpleNamespace(call=lambda operation,args:{'session':{},'family':{'status':'running'},'job':None} if operation=='lookup' else None)
    def deny(name,args):raise ValueError('MCP source transport/config changed; owner admission required')
    r.tool_policy=SimpleNamespace(classify=deny)
    decision=r.tool_control({'tool_name':'mcp__search__find','args':{}},session_id='synthetic')
    assert not decision.allow and decision.reason.startswith('GSD tool admission rejected:')
    assert 'timed out' not in decision.reason
