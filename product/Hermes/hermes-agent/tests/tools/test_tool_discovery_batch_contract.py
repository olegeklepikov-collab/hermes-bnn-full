"""The model-visible discovery batch limits must agree with the dispatcher."""
import json

import pytest
from jsonschema import Draft202012Validator


@pytest.mark.parametrize(('name', 'argument'), [('tool_search', 'queries'), ('tool_describe', 'names')])
def test_advertised_batch_boundary_matches_dispatch(name, argument):
    from tools.tool_search import bridge_tool_schemas, dispatch_tool_describe, dispatch_tool_search

    definition = next(item['function'] for item in bridge_tool_schemas(0) if item['function']['name'] == name)
    schema = definition['parameters']
    maximum = schema['properties'][argument]['maxItems']
    args = {argument: [f'mcp__batch_contract__item_{index}' for index in range(maximum)]}
    validator = Draft202012Validator(schema)
    validator.validate(args)
    dispatch = dispatch_tool_search if name == 'tool_search' else dispatch_tool_describe
    accepted = json.loads(dispatch(args, current_tool_defs=[]))
    assert 'error' not in accepted
    overflow = {argument: args[argument] + ['mcp__batch_contract__overflow']}
    assert not validator.is_valid(overflow)
    rejected = json.loads(dispatch(overflow, current_tool_defs=[]))
    assert 'too many' in rejected['error']
    assert f'max {maximum}' in rejected['error']
