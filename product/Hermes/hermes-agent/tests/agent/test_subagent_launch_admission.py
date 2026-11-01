"""Mandatory launch rejection and profile ownership before/through the native executor."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from agent.subagent_lifecycle import SubagentLifecycleService, SubagentLaunchRequest
from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
from hermes_cli.execution_control import ExecutionDecision, ExecutionControlDenied, register_control


def setup_service(monkeypatch, tmp_path, allow):
    home = tmp_path / 'routed-profile'
    home.mkdir()
    (home / 'execution-controls.json').write_text(json.dumps({'version': 1, 'required': {
        'subagent_launch': ['launch-probe']}, 'timeout_seconds': 5}))
    token = set_hermes_home_override(home)
    unregister = register_control('launch-probe', 'subagent_launch', lambda **kw: ExecutionDecision(allow, 'launch-test-denied'))
    parent = SimpleNamespace(session_id='parent', _current_turn_id='turn', enabled_toolsets=[])
    child = SimpleNamespace(session_id='child', _subagent_id=uuid.uuid4().hex, _delegate_role='leaf',
                            _delegate_depth=1, provider='test', model='test', close=Mock())
    observed = []
    monkeypatch.setattr('tools.delegate_tool._load_config', lambda: {})
    monkeypatch.setattr('tools.delegate_tool._resolve_delegation_credentials', lambda *a: {'model': 'test'})
    monkeypatch.setattr('tools.delegate_tool._credential_overrides', lambda *a: {})
    monkeypatch.setattr('tools.delegate_tool._build_child_preserving_parent_tools', lambda **kw: child)
    def run(*args):
        observed.append(get_hermes_home())
        return {'status': 'completed', 'summary': 'offline executor', 'api_calls': 0}
    monkeypatch.setattr('tools.delegate_tool._run_child_lifecycle', run)
    return home, token, unregister, SubagentLifecycleService(lambda: parent), child, observed


def test_denied_launch_does_not_start_executor(monkeypatch, tmp_path):
    home, token, unregister, service, child, observed = setup_service(monkeypatch, tmp_path, False)
    try:
        with pytest.raises(ExecutionControlDenied, match='launch-test-denied'):
            service.launch(SubagentLaunchRequest(goal='offline task'))
        assert observed == []
        child.close.assert_called_once()
    finally:
        unregister()
        reset_hermes_home_override(token)


def test_native_worker_preserves_routed_profile(monkeypatch, tmp_path):
    home, token, unregister, service, child, observed = setup_service(monkeypatch, tmp_path, True)
    try:
        handle = service.launch(SubagentLaunchRequest(goal='offline task'))
        result = service.wait(handle, timeout_seconds=5)
        assert result.completed
        assert service.result(handle).summary == 'offline executor'
        assert observed == [home]
    finally:
        unregister()
        reset_hermes_home_override(token)
