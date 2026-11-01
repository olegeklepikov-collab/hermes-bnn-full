"""Public child narrowing must use the same live toolset registry as the parent."""
from types import SimpleNamespace

import pytest


def test_explicit_empty_toolsets_do_not_inherit_parent_or_mcp(monkeypatch):
    from types import SimpleNamespace
    from tools import delegate_tool_toolsets as m
    monkeypatch.setattr(m, "_get_inherit_mcp_toolsets", lambda: True)
    parent = SimpleNamespace(enabled_toolsets=["terminal", "mcp_vendor"], disabled_toolsets=[])
    narrowed, _ = m._resolve_child_toolsets(parent, [], "leaf")
    assert narrowed == []
    inherited, _ = m._resolve_child_toolsets(parent, None, "leaf")
    assert "terminal" in inherited

from agent.subagent_lifecycle import SubagentLaunchRequest, SubagentLifecycleService, SubagentLifecycleError
from tools.registry import ToolRegistry


def test_registered_plugin_toolset_is_accepted_without_parent_broadening(monkeypatch):
    registry = ToolRegistry()
    monkeypatch.setattr("tools.registry.registry", registry)
    registry.register(name="fixture_plugin_read", toolset="fixture_plugin_scope", schema={
        "name": "fixture_plugin_read", "description": "A registered read tool.",
        "parameters": {"type": "object"},
    }, handler=lambda args: "{}")
    parent = SimpleNamespace(enabled_toolsets=["fixture_plugin_scope"])
    request = SubagentLaunchRequest(goal="Inspect", allowed_toolsets=("fixture_plugin_scope",))
    SubagentLifecycleService._validate_request(request, parent)
    with pytest.raises(SubagentLifecycleError, match="broaden"):
        SubagentLifecycleService._validate_request(request, SimpleNamespace(enabled_toolsets=["file"]))


@pytest.mark.parametrize("name", ["all", "*", "unregistered_fixture_scope"])
def test_global_or_unknown_toolset_is_not_a_child_narrowing(name):
    with pytest.raises(SubagentLifecycleError):
        SubagentLifecycleService._validate_request(
            SubagentLaunchRequest(goal="Inspect", allowed_toolsets=(name,)),
            SimpleNamespace(enabled_toolsets=None),
        )
