from types import SimpleNamespace

from agent.compression_checkpoint import (
    register_child_checkpoint_adapter, notify_checkpoint_compression_complete,
)
from hermes_constants import get_hermes_home


def test_observer_is_profile_bound_and_removed_on_unload():
    seen=[]
    undo=register_child_checkpoint_adapter('qualification',lambda *a: 'unused',profile_home=get_hermes_home(),
        on_compression_complete=lambda **kw:seen.append(kw))
    agent=SimpleNamespace(session_id='same',platform='subagent')
    try:
        assert notify_checkpoint_compression_complete(agent,new_session_id='same',old_session_id='same')
        assert seen==[{'session_id':'same','old_session_id':'same','platform':'subagent'}]
    finally:undo()
    assert not notify_checkpoint_compression_complete(agent,new_session_id='same',old_session_id='same')


def test_different_native_session_cannot_mint_commit():
    import pytest
    with pytest.raises(ValueError,match='session_mismatch'):
        notify_checkpoint_compression_complete(SimpleNamespace(session_id='actual'),new_session_id='forged',old_session_id='actual')
