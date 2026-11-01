"""Required controller denials must survive registry error normalization."""
import json

import pytest

from hermes_cli.execution_control import ExecutionControlDenied, ExecutionDecision, register_control
from tools.registry import ToolRegistry


@pytest.mark.parametrize('origin', ['registry', 'nested_handler'])
def test_mandatory_denial_reaches_caller_without_product_or_effect(tmp_path, monkeypatch, origin):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'execution-controls.json').write_text(json.dumps({
        'version': 1, 'required': {'tool': ['fixture-denial']}, 'timeout_seconds': 5}))
    release = register_control('fixture-denial', 'tool', lambda **kw:
        ExecutionDecision(origin != 'registry', 'fixture-unknown-previous-outcome'))
    effect = tmp_path / 'should-not-exist.txt'
    registry = ToolRegistry()
    def handler(args):
        if origin == 'nested_handler':
            raise ExecutionControlDenied('fixture-nested-required-denial')
        effect.write_text('unexpected effect')
        return '{}'
    registry.register(name='fixture', toolset='fixture', schema={'name': 'fixture'}, handler=handler)
    try:
        with pytest.raises(ExecutionControlDenied, match='fixture-'):
            registry.dispatch('fixture', {})
        assert not effect.exists()
    finally:
        release()


def test_ordinary_handler_error_remains_json_tool_result(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    registry = ToolRegistry()
    def handler(args):
        raise ValueError('fixture ordinary failure')
    registry.register(name='fixture', toolset='fixture', schema={'name': 'fixture'}, handler=handler)
    assert 'fixture ordinary failure' in json.loads(registry.dispatch('fixture', {}))['error']
