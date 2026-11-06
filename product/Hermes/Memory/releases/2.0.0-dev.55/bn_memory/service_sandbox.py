"""Shared local-service isolation policy. R gets only its own per-session state."""
from pathlib import Path
import json
def profile(root,entry,method=None):
 root=Path(root);scope=entry.get('_runtime_state_root',entry['state_root']);q=lambda p:json.dumps(str(p))
 text='(version 1)(allow default)(deny file-read* (subpath '+q(root.parent/'Hermes BN')+') (subpath '+q(root.parent/'Hermes UDR')+'))'
 text+='(deny file-write* (require-all (require-not (subpath '+q(scope)+')) (require-not (literal "/dev/null"))))'
 for p in [root/'data/auth.json',root/'Identity/authority']:
  text+='(deny file-read-data (subpath '+q(p)+'))'
 text+='(deny file-read-data (require-all (subpath '+q(root/'state/authority')+') (require-not (literal '+q(entry['authority_file'])+'))))'
 if entry['service']=='asreview':text+='(deny network*)'
 if entry.get('untrusted_evaluator'):
  code=Path(entry['state_root']);allowed=[('subpath',code/'framework-library'),('subpath',root/'R/serena-library'),('subpath',root/'runtime/python'),('subpath',scope)]
  allowed += [('literal',code/x) for x in ['r_launch.py','bootstrap.R','server.R']]
  allowed += [('literal',x['path']) for x in entry.get('_input_snapshots',[])]
  allowed += [('literal',x) for x in entry.get('_input_allowed_files',[])]
  if entry.get('_input_read_root'):allowed.append(('subpath',entry['_input_read_root']))
  text+='(deny file-read-data (require-all (require-any (subpath "/Users") (subpath "/Volumes") (subpath "/private/tmp") (subpath "/private/var/folders") (subpath "/Library/Keychains")) '+''.join('(require-not ('+kind+' '+q(p)+'))' for kind,p in allowed)+'))(deny process-fork)(deny process-info* (require-not (target self)))'
  if entry.get('_input_read_root'):text+='(deny file-write* (subpath '+q(entry['_input_read_root'])+'))'
  if method and method.startswith('btw_tool_cran_'):
   text+='(deny network-inbound)(deny network-outbound (require-all (require-not (remote tcp "*:443")) (require-not (remote udp "*:53"))))'
  else:text+='(deny network*)'
 return text
