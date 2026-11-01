"""Finite service integration operator for this BNN only, never a model shell."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'Development/services-20261028'
def main(argv):
 if argv==['tinyfish-mcp-check']:
  from service_tinyfish_check import mcp
  return mcp()
 if argv==['tinyfish-check']:
  from service_tinyfish_check import run
  return run()
 if argv==['synapse-check']:
  from service_synapse_check import run
  return run()
 if len(argv)==2 and argv[0]=='remote-secret':
  from service_remote_secret import receive
  try:return receive(argv[1])
  except Exception as exc:raise RuntimeError('Remote secret import stopped: '+type(exc).__name__+'; plaintext not displayed') from None
 if argv==['dory-check']:
  from service_dory_check import run
  return run()
 if argv==['extensions-prepare']:
  from service_extensions import prepare
  return prepare()
 if argv==['extensions-stage']:
  from service_extensions import stage_registry
  return stage_registry()
 if argv==['protected-keys']:
  from service_key_form import serve
  return serve()
 if argv==['public-check']:
  from service_public_check import run
  return run()
 if argv==['extension-team-check']:
  from service_extension_team import run
  return run()
 if argv==['extension-team-proof']:
  from service_extension_team import verify_saved_delivery
  return verify_saved_delivery()
 if argv==['status']:
  from service_extensions import status
  return status()
 if argv and argv[0] in {'pending','reconcile-not-performed'}:
  from service_recovery import command
  return command(argv)
 if argv in [['zotero-bind'],['zotero-authorize']]:
  from service_local_setup import zotero
  return zotero(argv==['zotero-authorize'])
 if argv==['timeout-check']:
  from service_timeout_probe import run
  return run()
 if len(argv)==1 and argv[0] in {'archive-verify','release-split','publish'}:
  from service_publish import verify,split,publish
  return {'archive-verify':verify,'release-split':split,'publish':publish}[argv[0]]()
 if argv==['report']:
  from service_finish_report import report
  return report()
 if argv==['audit-distribution']:
  from service_distribution_audit import audit
  return audit()
 if argv==['distribution']:
  from service_distribution import prepare
  return prepare()
 if argv==['docs']:
  from service_docs import harvest
  return harvest()
 if argv==['inventory']:
  from service_inventory import inventory
  return inventory()
 if argv==['discover']:
  from service_inventory import discover
  return discover()
 if argv==['build']:
  from service_release import build
  return build()
 if argv==['revise']:
  from service_release import revise
  return revise()
 if argv==['activate']:
  from service_release import activate
  return activate()
 if argv==['contracts']:
  import subprocess,sys
  r=subprocess.run([sys.executable,str(ROOT/'Development/service_contracts.py')],cwd=ROOT)
  if r.returncode:raise RuntimeError('service_contract_process_failed')
  return json.loads((BASE/'contracts-status.json').read_text())
 if argv==['r-probe']:
  from service_inventory import r_probe
  return r_probe()
 if argv==['r-install']:
  from service_r_install import install
  return install()
 if argv==['plans']:
  from service_review import generate
  return generate()
 if argv==['qualify']:
  from service_qualification import native
  return native()
 if len(argv)==2 and argv[0]=='oauth':
  from service_auth import authorize
  return authorize(argv[1])
 if len(argv)==2 and argv[0]=='discover-one':
  from service_auth import discover_one
  return discover_one(argv[1])
 if len(argv)==2 and argv[0]=='setup-key':
  from service_auth import configure_key
  return configure_key(argv[1])
 if argv==['contact']:
  from service_auth import contact
  return contact()
 if len(argv)==2 and argv[0]=='system-check':
  from service_systemcheck import run
  return run(argv[1])
 if argv==['status']:
  return {p.name:json.loads(p.read_text()) for p in BASE.glob('*status.json')}
 raise ValueError('services: inventory | docs | discover | status')
