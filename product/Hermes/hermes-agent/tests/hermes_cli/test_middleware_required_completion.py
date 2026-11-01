"""Required completion refusal must not be hidden by optional middleware fallback."""
import pytest

from hermes_cli import plugins
from hermes_cli.execution_control import ExecutionControlDenied
from hermes_cli.middleware import run_llm_execution_middleware, run_tool_execution_middleware
from hermes_cli.plugins import PluginManager, PluginContext, PluginManifest


@pytest.mark.parametrize('kind', ['llm_execution', 'tool_execution'])
@pytest.mark.parametrize('after_executor', [False, True])
def test_required_middleware_refusal_never_becomes_success(tmp_path, monkeypatch, kind, after_executor):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    manager = PluginManager(); monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: manager)
    context = PluginContext(PluginManifest(name='fixture', source='user'), manager)
    calls = []
    def middleware(next_call, **kw):
        if after_executor: next_call()
        raise ExecutionControlDenied('fixture completion receipt unavailable')
    context.register_middleware(kind, middleware)
    def execute(payload): calls.append(payload); return {'result': 'actual returned value'}
    with pytest.raises(ExecutionControlDenied, match='completion receipt'):
        if kind == 'llm_execution': run_llm_execution_middleware({'messages': []}, execute)
        else: run_tool_execution_middleware('fixture', {'value': 1}, execute)
    assert len(calls) == int(after_executor)


def test_ordinary_optional_post_middleware_failure_preserves_single_return(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    manager = PluginManager(); monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: manager)
    context = PluginContext(PluginManifest(name='fixture', source='user'), manager)
    calls = []
    def middleware(next_call, **kw):
        next_call(); raise ValueError('optional observer failed')
    context.register_middleware('tool_execution', middleware)
    assert run_tool_execution_middleware('fixture', {}, lambda args: calls.append(args) or 'returned') == 'returned'
    assert calls == [{}]
