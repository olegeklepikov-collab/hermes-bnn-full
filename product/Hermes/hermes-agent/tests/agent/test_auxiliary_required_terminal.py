"""Required policy observes the real post-relay auxiliary request."""
from types import SimpleNamespace
import json
import pytest


def test_auxiliary_rewrite_is_checked_before_observed_provider(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux, relay_llm
    from hermes_cli.execution_control import ExecutionDecision, register_control
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "execution-controls.json").write_text(json.dumps({"version": 1,
        "required": {"auxiliary": ["fixture"]}, "timeout_seconds": 1}))
    monkeypatch.setattr(aux, "_relay_auxiliary_metadata", lambda **kw: ("fixture", "model", {
        "api_request_id": "physical", "auxiliary_task": "test"}))
    monkeypatch.setattr(relay_llm, "execute_current", lambda request, callback, **kw: callback({**request, "rewritten": True}))
    observed = []
    remove = register_control("fixture", "auxiliary", lambda payload, **kw: observed.append(payload) or ExecutionDecision(False))
    marker = tmp_path / "provider-effect"
    try:
        with pytest.raises(PermissionError):
            aux._relay_sync_completion(SimpleNamespace(), {"model": "model", "messages": []},
                create=lambda request: marker.write_text("executed"))
        assert observed[0]["request"]["rewritten"] is True
        assert not marker.exists()
    finally:
        remove()


def test_explicit_codex_output_bound_survives_real_adapter_conversion():
    from agent.auxiliary_client import _CodexCompletionsAdapter
    client = SimpleNamespace(base_url="https://chatgpt.com/backend-api/codex", _hermes_aux_effective_provider="openai-codex")
    adapter = _CodexCompletionsAdapter(client, "gpt-6.1-sol")
    request, _, _ = adapter._build_responses_kwargs({"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "bounded"}],
                                                    "max_output_tokens": 512})
    assert request["max_output_tokens"] == 512


def test_unattributed_auxiliary_cannot_bypass_missing_control(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "execution-controls.json").write_text(json.dumps({"version": 1,
        "required": {"auxiliary": ["absent"]}, "timeout_seconds": 1}))
    marker = tmp_path / "effect"
    with pytest.raises(PermissionError):
        aux._relay_sync_completion(SimpleNamespace(), {"messages": []}, create=lambda request: marker.write_text("executed"))
    assert not marker.exists()
