"""Required execution policy must survive missing plugins and observer failures."""
import json
from pathlib import Path

import pytest

from tools.registry import ToolRegistry
from hermes_cli.execution_control import ExecutionControlDenied


def configure(home, kind="tool", controller="fixture"):
    home.mkdir(parents=True, exist_ok=True)
    (home / "execution-controls.json").write_text(json.dumps({
        "version": 1, "required": {kind: [controller]}, "timeout_seconds": 0.05,
    }))


def marker_registry(path):
    registry = ToolRegistry()
    def effect(args):
        path.write_text(args["value"])
        return json.dumps({"written": True})
    registry.register(name="controlled_effect", toolset="fixture", schema={
        "name": "controlled_effect", "description": "Local controlled effect.",
        "parameters": {"type": "object"},
    }, handler=effect)
    return registry


def test_missing_required_controller_prevents_real_effect(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    marker = tmp_path / "effect.txt"
    registry = marker_registry(marker)
    # Positive control: the actual executor works before policy is required.
    assert json.loads(registry.dispatch("controlled_effect", {"value": "control"}))["written"]
    assert marker.read_text() == "control"
    marker.unlink()
    configure(home)
    with pytest.raises(ExecutionControlDenied, match='unavailable'):
        registry.dispatch("controlled_effect", {"value": "forbidden"})
    assert not marker.exists()


def test_context_scoped_multiplex_A_B_A_uses_own_controller(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.execution_control import ExecutionDecision, register_control
    a, b = tmp_path / "A", tmp_path / "B"
    configure(a); configure(b); monkeypatch.setenv("HERMES_HOME", str(a))
    observations, removers = [], []
    for home, label in [(a, "A"), (b, "B")]:
        token = set_hermes_home_override(home)
        try:
            removers.append(register_control("fixture", "tool", lambda _label=label, **kw: observations.append(_label) or ExecutionDecision(True)))
        finally:
            reset_hermes_home_override(token)
    marker = tmp_path / "real-effect"
    registry = marker_registry(marker)
    try:
        for home, label in [(a, "A"), (b, "B"), (a, "A")]:
            token = set_hermes_home_override(home)
            try:
                assert json.loads(registry.dispatch("controlled_effect", {"value": label}))["written"]
                assert marker.read_text() == label
            finally:
                reset_hermes_home_override(token)
        assert observations == ["A", "B", "A"]
    finally:
        for remove in removers: remove()


def test_direct_connector_dispatch_cannot_bypass_required_control(tmp_path, monkeypatch):
    from tools.connectors.dispatch import dispatch_connector_call
    monkeypatch.setenv("HERMES_HOME", str(tmp_path)); configure(tmp_path)
    marker = tmp_path / "remote-side-effect"
    monkeypatch.setattr("tools.connectors.gateway.bridge.run_remote", lambda *a, **k: marker.write_text("called"))
    with pytest.raises(PermissionError):
        dispatch_connector_call("connectors__fixture_write", {"value": "no"}, "call1", session_id="owner")
    assert not marker.exists()


def test_required_model_controller_prevents_provider_fallback(tmp_path, monkeypatch):
    from hermes_cli.middleware import run_llm_execution_middleware
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    configure(home, "llm")
    effect = tmp_path / "provider_was_called"
    def provider(request):
        effect.write_text("called")
        return {"response": "ok"}
    with pytest.raises(PermissionError):
        run_llm_execution_middleware({"messages": []}, provider, session_id="s")
    assert not effect.exists()


@pytest.mark.parametrize("failure", ["deny", "raise", "timeout", "invalid_return", "system_exit"])
def test_failed_required_controller_never_falls_through(tmp_path, monkeypatch, failure):
    import time
    from hermes_cli.execution_control import ExecutionDecision, register_control
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    configure(home)
    marker = tmp_path / "effect.txt"
    registry = marker_registry(marker)
    def control(**kw):
        if failure == "raise":
            raise RuntimeError("synthetic controller failure")
        if failure == "system_exit":
            raise SystemExit(0)
        if failure == "timeout":
            time.sleep(0.2)
            return ExecutionDecision(True)
        if failure == "invalid_return":
            return {"allow": True}
        return ExecutionDecision(False, "denied")
    remove = register_control("fixture", "tool", control)
    try:
        with pytest.raises(ExecutionControlDenied):
            registry.dispatch("controlled_effect", {"value": "forbidden"})
        assert not marker.exists()
    finally:
        remove()


def test_registration_is_profile_scoped_and_removal_is_closed(tmp_path, monkeypatch):
    from hermes_cli.execution_control import ExecutionDecision, register_control
    a, b = tmp_path / "A", tmp_path / "B"
    configure(a)
    configure(b)
    marker = tmp_path / "effect.txt"
    registry = marker_registry(marker)
    monkeypatch.setenv("HERMES_HOME", str(a))
    remove = register_control("fixture", "tool", lambda **kw: ExecutionDecision(True))
    try:
        assert json.loads(registry.dispatch("controlled_effect", {"value": "A"}))["written"]
        marker.unlink()
        monkeypatch.setenv("HERMES_HOME", str(b))
        with pytest.raises(ExecutionControlDenied, match='unavailable'):
            registry.dispatch("controlled_effect", {"value": "B"})
        assert not marker.exists()
        monkeypatch.setenv("HERMES_HOME", str(a))
        assert json.loads(registry.dispatch("controlled_effect", {"value": "A-again"}))["written"]
        marker.unlink()
    finally:
        remove()
    with pytest.raises(ExecutionControlDenied, match='unavailable'):
        registry.dispatch("controlled_effect", {"value": "unloaded"})
    assert not marker.exists()


def test_middleware_failure_cannot_remove_terminal_control(tmp_path, monkeypatch):
    from hermes_cli.plugins import _delivery_manager
    from hermes_cli.middleware import run_tool_execution_middleware
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    configure(home)
    manager = _delivery_manager()
    def broken(**kw):
        raise ValueError("fault injected before next_call")
    monkeypatch.setitem(manager._middleware, "tool_execution", [broken])
    marker = tmp_path / "effect"
    with pytest.raises(PermissionError):
        run_tool_execution_middleware("controlled_effect", {}, lambda args: marker.write_text("bad"))
    assert not marker.exists()


def test_auxiliary_provider_cannot_bypass_required_control(tmp_path, monkeypatch):
    from agent.auxiliary_hooks import run_with_aux_hooks
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    configure(home, "auxiliary")
    marker = tmp_path / "effect"
    with pytest.raises(PermissionError):
        run_with_aux_hooks(lambda: marker.write_text("bad"), aux_task="test", metadata={},
                           client=None, kwargs={"messages": []}, provider="synthetic",
                           model="synthetic", api_mode="chat_completions")
    assert not marker.exists()


def test_required_result_control_closes_evidence_delivery_after_real_executor(tmp_path,monkeypatch):
    from hermes_cli.middleware import run_tool_execution_middleware
    from hermes_cli.execution_control import ExecutionDecision,register_control
    monkeypatch.setenv('HERMES_HOME',str(tmp_path));configure(tmp_path,'tool_result')
    calls=[]
    with pytest.raises(PermissionError):
        run_tool_execution_middleware('read_source',{},lambda args:calls.append('actual') or 'evidence')
    assert calls==['actual']
    remove=register_control('fixture','tool_result',lambda **kw:ExecutionDecision(True))
    try:
        assert run_tool_execution_middleware('read_source',{},lambda args:'checked-delivery')=='checked-delivery'
    finally:remove()


def test_missing_policy_is_closed_in_fresh_process_from_operator_declaration(tmp_path):
    import os,subprocess,sys
    home=tmp_path/'new-profile';home.mkdir()
    (home/'config.yaml').write_text('execution_controls_required: true\n')
    marker=tmp_path/'must-not-run'
    code='from hermes_cli.middleware import run_tool_execution_middleware\nfrom pathlib import Path\nrun_tool_execution_middleware("effect",{},lambda args:Path('+repr(str(marker))+').write_text("bad"))'
    p=subprocess.run([sys.executable,'-c',code],env={**os.environ,'HERMES_HOME':str(home)},capture_output=True,text=True)
    assert p.returncode!=0 and not marker.exists()
    assert 'mandatory execution policy is missing' in p.stderr
