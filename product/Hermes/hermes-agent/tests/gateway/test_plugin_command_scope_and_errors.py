"""Isolated reproduction of command failure masking and routed profile scope.

No provider calls, Telegram transport, production homes or GSD state are used.
Tests specify the required behaviour; failures are audit findings, not acceptance.
"""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner, _profile_runtime_scope
from gateway.session import SessionSource
from gateway.session_identity import RoutingIdentity
from hermes_cli import plugins, profiles
from hermes_constants import get_hermes_home
from tests.gateway.test_unknown_command import _make_event, _make_runner


REASON = "Resume cannot renew the deadline or reset spent resource"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_handler", [False, True])
async def test_registered_handler_refusal_is_not_unknown(monkeypatch, async_handler):
    runner = _make_runner()
    def sync_handler(args):
        raise RuntimeError(REASON)
    async def async_fn(args):
        raise RuntimeError(REASON)
    handler = async_fn if async_handler else sync_handler
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: handler if name == "gsd" else None)
    reply = await runner._handle_message(_make_event("/gsd resume"))
    assert reply is not None
    assert "Unknown command" not in reply, reply
    assert REASON in reply, reply


@pytest.mark.asyncio
async def test_absent_command_remains_unknown(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: None)
    reply = await runner._handle_message(_make_event("/not-a-real-audit-command"))
    assert "Unknown command" in reply


@pytest.mark.asyncio
async def test_command_lookup_failure_is_terminal(monkeypatch):
    runner = _make_runner()
    def unavailable(name):
        raise RuntimeError("Registry unavailable")
    monkeypatch.setattr(plugins, "get_plugin_command_handler", unavailable)
    reply = await runner._handle_message(_make_event("/gsd resume"))
    assert "Registry unavailable" in reply
    assert "Unknown command" not in reply


@pytest.mark.asyncio
async def test_command_error_redacts_reply_and_log(monkeypatch, caplog):
    runner = _make_runner()
    key = "sk-test123456789012345678901234567890"
    bearer = "opaqueBearer12345678901234567890"
    def refused(args):
        raise RuntimeError(f"{REASON}; api_key={key}; Authorization: Bearer {bearer}")
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: refused)
    reply = await runner._handle_message(_make_event("/gsd resume"))
    assert REASON in reply
    assert key not in reply and bearer not in reply
    assert key not in caplog.text and bearer not in caplog.text


@pytest.mark.asyncio
async def test_cancellation_is_propagated(monkeypatch):
    runner = _make_runner()
    async def cancelled(args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: cancelled)
    with pytest.raises(asyncio.CancelledError):
        await runner._hm_dispatch_quick_and_plugin_commands(_make_event("/gsd status"), _make_event("/gsd status").source, "gsd")


@pytest.mark.asyncio
async def test_failed_mandatory_scope_blocks_handler(monkeypatch):
    runner = _make_runner()
    calls = []
    @asynccontextmanager
    async def failed_scope(source):
        raise RuntimeError("Scope unavailable")
        yield
    monkeypatch.setattr(runner, "_async_profile_scope_for_source", failed_scope)
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: calls.append(name))
    event = _make_event("/gsd status")
    with pytest.raises(RuntimeError, match="Scope unavailable"):
        await runner._hm_dispatch_quick_and_plugin_commands(event, event.source, "gsd")
    assert calls == []


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    homes = {name: root / "profiles" / name for name in ("gsd", "udr")}
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(tmp_path / "empty-bundled"))
    monkeypatch.delenv("HERMES_ENABLE_PROJECT_PLUGINS", raising=False)
    monkeypatch.setattr(profiles, "get_profile_dir", lambda name: homes[name])
    monkeypatch.setattr(profiles, "profile_exists", lambda name: name in homes)
    monkeypatch.chdir(tmp_path)
    plugins._reset_plugin_managers_for_tests()
    for name, home in homes.items():
        directory = home / "plugins" / "audit-commands"
        directory.mkdir(parents=True)
        (home / "config.yaml").write_text(json.dumps({"plugins": {"enabled": ["audit-commands"]}}))
        (directory / "plugin.yaml").write_text("name: audit-commands\nversion: 1.0.0\n")
        (directory / "__init__.py").write_text(
            "from hermes_constants import get_hermes_home\n"
            "def register(ctx):\n"
            f"    ctx.register_command('audit-owner', lambda args: {name!r} + ':' + get_hermes_home().name)\n"
            f"    ctx.register_command('audit-{name}', lambda args: {name!r})\n"
        )
    try:
        yield root, homes
    finally:
        plugins._reset_plugin_managers_for_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("gsd", "udr"), ("udr", "gsd")])
@pytest.mark.parametrize("routed", [False, True])
async def test_multiplex_handler_uses_runtime_profile(isolated_profiles, order, routed):
    root, homes = isolated_profiles
    for name in order:
        with _profile_runtime_scope(homes[name]):
            assert plugins.get_plugin_command_handler("audit-owner") is not None
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    runner._draining = False
    runner._primary_profile_name = "default"
    observations = []
    async def dispatch(event):
        result = await runner._hm_dispatch_quick_and_plugin_commands(event, event.source, "audit_owner")
        observations.append(result)
        return result
    runner._handle_message = dispatch
    try:
        for transport in order:
            runtime = ("udr" if transport == "gsd" else "gsd") if routed else transport
            source = SessionSource(platform=Platform.TELEGRAM, chat_id="synthetic", user_id="synthetic", chat_type="dm", profile=runtime)
            source._identity = RoutingIdentity(transport_profile=transport, runtime_profile=runtime,
                authorization_home=homes[transport], runtime_home=homes[runtime])
            event = MessageEvent(text="/audit_owner", source=source, message_id="synthetic")
            result = await runner._make_profile_message_handler(transport)(event)
            assert result[0] is True, result
            assert result[1] == f"{runtime}:{runtime}", {
                "transport": transport, "runtime": runtime, "actual": result,
            }
        assert get_hermes_home() == root
    finally:
        executor = getattr(runner, "_executor", None)
        if executor is not None:
            executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_routed_profile_only_command_is_discovered(isolated_profiles):
    _, homes = isolated_profiles
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    runner._draining = False
    runner._primary_profile_name = "default"
    async def dispatch(event):
        return await runner._hm_dispatch_quick_and_plugin_commands(event, event.source, "audit_udr")
    runner._handle_message = dispatch
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="synthetic", user_id="synthetic", chat_type="dm", profile="udr")
    source._identity = RoutingIdentity(transport_profile="gsd", runtime_profile="udr",
        authorization_home=homes["gsd"], runtime_home=homes["udr"])
    result = await runner._make_profile_message_handler("gsd")(
        MessageEvent(text="/audit_udr", source=source, message_id="synthetic"))
    assert result == (True, "udr", "audit_udr"), result
