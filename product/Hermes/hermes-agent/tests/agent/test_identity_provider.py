"""Managed identity uses the native stable slot and the explicit owning profile."""
from types import SimpleNamespace
import pytest
from agent.identity_provider import register_identity_provider,resolve_identity,IdentityProjection
from agent.system_prompt import _identity_parts
from hermes_constants import get_hermes_home,set_hermes_home_override,reset_hermes_home_override


def test_explicit_profile_a_b_a_is_bound_and_ambient_home_restored(tmp_path):
    a,b=tmp_path/'A',tmp_path/'B';a.mkdir();b.mkdir()
    seen=[];removers=[]
    for home in [a,b]:
        def callback(agent,context_length=None,expected=home):
            seen.append(get_hermes_home().resolve())
            assert get_hermes_home().resolve()==expected
            return IdentityProjection(expected.name,{'profile':expected.name})
        removers.append(register_identity_provider(home,callback))
    token=set_hermes_home_override(b)
    try:
        assert [resolve_identity(None,home).text for home in [a,b,a]]==['A','B','A']
        assert get_hermes_home().resolve()==b
        assert seen==[a,b,a]
    finally:
        reset_hermes_home_override(token)
        for remove in removers:remove()


def test_managed_provider_failure_does_not_fall_back_to_builtin_identity(tmp_path):
    def unavailable(agent,context_length=None):raise PermissionError('required identity unavailable')
    remove=register_identity_provider(tmp_path,unavailable);token=set_hermes_home_override(tmp_path)
    try:
        with pytest.raises(PermissionError,match='required identity'):
            _identity_parts(SimpleNamespace(load_soul_identity=False,skip_context_files=True),None)
    finally:
        remove();reset_hermes_home_override(token)


def test_empty_managed_projection_is_not_identity_delivery(tmp_path):
    remove=register_identity_provider(tmp_path,lambda agent,context_length=None:IdentityProjection('',{}))
    try:
        with pytest.raises(PermissionError):resolve_identity(None,tmp_path)
    finally:remove()
