"""Operator-owned exact catalogue, bound to actual configured MCP transports."""
from pathlib import Path
import hashlib
from .codec import canonical,read_json,digest


def transport_digest(config):
    return digest(config)


class ToolPolicy:
    def __init__(self,settings):
        self.settings=settings
        path=Path(settings['tool_policy'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=settings['tool_policy_sha256']:raise ValueError('Tool admission policy changed')
        self.policy=read_json(path.read_bytes())
        for name,sha in settings.get("local_adapter_sha256",{}).items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=sha:raise ValueError("Admitted local adapter changed: "+name)
        if self.policy.get('version')!=1:raise ValueError('Unknown tool policy')
    def classify(self,name,args):
        row=self.policy['entries'].get(name)
        if not row:return None
        from hermes_cli.config import read_user_config_raw, _expand_env_vars
        from agent.secret_scope import current_secret_scope_home
        from hermes_constants import get_hermes_home
        scoped_home = current_secret_scope_home()
        if scoped_home and Path(scoped_home).resolve() != get_hermes_home().resolve():
            raise ValueError('MCP credential scope belongs to another profile')
        from hermes_cli.config_effective import load_user_config_effective
        raw = read_user_config_raw().get('mcp_servers', {}).get(row['server'])
        admitted = self.settings['mcp_transport_digests'].get(row['server'])
        if not raw or transport_digest(raw) != admitted:
            raise ValueError('MCP source transport/config changed; owner admission required')
        # The admission binds the literal configuration and its credential references.
        # Expand those admitted references through the native active profile scope,
        # then compare to the exact effective configuration used by the MCP client.
        expected = _expand_env_vars(raw)
        from .codec import strings
        import re
        if any(re.search(r'\$\{(?:env:)?[A-Za-z_][A-Za-z0-9_]*\}', value) for value in strings(expected)):
            raise ValueError('MCP configuration has an unresolved profile credential/environment reference')
        config = load_user_config_effective(fail_closed=True).get('mcp_servers', {}).get(row['server'])
        if not config or transport_digest(config) != transport_digest(expected):
            raise ValueError('MCP effective transport differs from admitted profile configuration')
        from tools import mcp_tool
        # Provenance is captured by the native registry, never inferred from a model-supplied name.
        if mcp_tool._mcp_tool_server_names.get(name)!=row['server']:
            raise ValueError('Registered MCP provenance does not match the admitted server')
        if len(canonical(args))>262144:raise ValueError('Tool input exceeds admitted bound; split independent work')
        if name=='mcp__firecrawl__firecrawl_scrape' and args.get('actions'):
            row={**row,'mode':'exact_owner_grant'}
        return row
