from pathlib import Path
import json,sys,os,yaml
Z=Path(__file__).resolve().parents[1];R=Z.parent;B=R/'Beads';sys.path.insert(0,str(Z));from scoped_mcp import BEADS,DOLT;from workspace_api import OPS
p=R/'data/config.yaml';before=yaml.safe_load((B/'config/hermes-before.yaml').read_text());current=yaml.safe_load(p.read_text());assert current==before,'Compare user config changes before installing new servers'
new={'beads':{'command':str(R/'bin/beads-bn-scoped-mcp'),'args':[],'enabled':True,'connect_timeout':60,'tool_timeout':180,'tools':{'include':sorted(BEADS)}},'dolt':{'command':str(R/'bin/dolt-bn-mcp'),'args':[],'enabled':True,'connect_timeout':45,'tool_timeout':180,'tools':{'include':sorted(DOLT)}},'beads-dolt':{'command':str(R/'bin/beads-dolt-bn-mcp'),'args':[],'enabled':True,'connect_timeout':45,'tool_timeout':300,'tools':{'include':list(OPS)}}}
for name,cfg in new.items():assert name not in current['mcp_servers'];current['mcp_servers'][name]=cfg
check={**current,'mcp_servers':dict(current['mcp_servers'])}
for name in new:check['mcp_servers'].pop(name)
assert check==before
tmp=p.with_suffix('.beads-dolt.tmp');tmp.write_text(yaml.safe_dump(current,allow_unicode=True,sort_keys=False));tmp.chmod(0o600);os.replace(tmp,p)
(Z/'checks/config-preservation.json').write_text(json.dumps({'previous_servers':len(before['mcp_servers']),'new_servers':len(current['mcp_servers']),'all_previous_servers_and_settings_unchanged':True,'beads_methods':len(BEADS),'dolt_methods':len(DOLT),'workspace_methods':len(OPS),'total_selected_methods':len(BEADS)+len(DOLT)+len(OPS)},indent=2));print('Hermes servers added, original configuration preserved; selected methods',len(BEADS)+len(DOLT)+len(OPS))
