from types import SimpleNamespace
from unittest.mock import patch
import toolsets

def test_dynamic_plugin_and_mcp_alias_share_surface_without_shadowing():
    names={'udr':['bn_deliver_report'],'mcp-udr':['mcp__udr__udr_research','mcp__udr__udr_status']}
    fake=SimpleNamespace(get_tool_names_for_toolset=lambda n:names.get(n,[]),get_toolset_alias_target=lambda n:'mcp-udr' if n=='udr' else None)
    with patch.object(toolsets,'_registry',return_value=fake),patch.object(toolsets,'_get_plugin_toolset_names',return_value=set(names)),patch.object(toolsets,'_get_registry_toolset_aliases',return_value={'udr':'mcp-udr'}):
        result=toolsets.get_toolset('udr')
    assert set(result['tools'])=={'bn_deliver_report','mcp__udr__udr_research','mcp__udr__udr_status'}

def test_alias_does_not_add_unrelated_tools_or_change_static_only_lookup():
    fake=SimpleNamespace(get_tool_names_for_toolset=lambda n:['own'] if n=='my-plugin' else ['unrelated'],get_toolset_alias_target=lambda n:None)
    with patch.object(toolsets,'_registry',return_value=fake),patch.object(toolsets,'_get_plugin_toolset_names',return_value={'my-plugin'}),patch.object(toolsets,'_get_registry_toolset_aliases',return_value={}):
        assert toolsets.get_toolset('my-plugin')['tools']==['own']
        assert toolsets.get_toolset('my-plugin',include_registry=False) is None
