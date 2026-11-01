"""Native completion cannot be skipped by middleware and cannot re-enter admission."""
import pytest

from agent.tool_attempt import current_tool_attempt, tool_attempt_scope, register_tool_completion
from hermes_cli.execution_control import ExecutionControlDenied


def test_completion_runs_once_after_native_scope_closes(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path)); calls = []
    def complete(attempt):
        assert not attempt.active.is_set()
        with pytest.raises(PermissionError): register_tool_completion('recursive', complete)
        calls.append(attempt.nonce)
    with tool_attempt_scope('fixture', {'session_id': 'parent'}) as attempt:
        register_tool_completion('fixture', complete)
        register_tool_completion('fixture', complete)
        assert calls == []
    assert calls == [attempt.nonce]
    assert current_tool_attempt() is None


@pytest.mark.parametrize('error', [RuntimeError, SystemExit])
def test_required_completion_failure_runs_other_receipts_and_denies_result(tmp_path, monkeypatch, error):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path)); calls = []
    def failed(attempt): raise error('synthetic persistence failure')
    with pytest.raises(ExecutionControlDenied, match='required_tool_completion_failed'):
        with tool_attempt_scope('fixture', {}):
            register_tool_completion('failed', failed)
            register_tool_completion('other', lambda attempt: calls.append(attempt.nonce))
    assert len(calls) == 1
    assert current_tool_attempt() is None


def test_no_unscoped_or_conflicting_completion_authority(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    with pytest.raises(PermissionError): register_tool_completion('fixture', lambda attempt: None)
    with tool_attempt_scope('fixture', {}):
        register_tool_completion('fixture', lambda attempt: None)
        with pytest.raises(ValueError): register_tool_completion('fixture', lambda attempt: None)
