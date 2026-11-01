#!/usr/bin/env python3
"""Restore an explicit pre-GSD snapshot; retain all GSD state/keys and user baseline changes."""
from pathlib import Path
import argparse,json,shutil,hashlib,subprocess,sys


def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--backup',required=True);p.add_argument('--expected-config-sha256');p.add_argument('--apply',action='store_true');a=p.parse_args()
 root=Path(a.runtime_root).resolve();backup=Path(a.backup).resolve();receipt=json.loads((backup/'receipt.json').read_text())
 plan={'runtime':str(root),'backup':str(backup),'core_files':receipt['modified_paths'],'profile':['config.yaml','execution-controls.json','runtime-manager.json','.env'],'gsd_state_kept':True,'credentials_outside_snapshot_unchanged':True,'apply':a.apply}
 if not a.apply:print(json.dumps(plan,ensure_ascii=False,indent=2));return
 if not a.expected_config_sha256 or hashlib.sha256((root/'data/config.yaml').read_bytes()).hexdigest()!=a.expected_config_sha256:raise ValueError('Current configuration must match an explicitly reviewed fingerprint')
 subprocess.run([str(root/'bin/hermes-bn-telegram'),'stop'],check=True)
 import psutil
 for process in psutil.process_iter(['pid','cmdline']):
  if process.pid==__import__('os').getpid():continue
  args=process.info['cmdline'] or []
  if any(str(root/'app-build') in arg for arg in args) and process.info['cmdline'][0].endswith('/MacOS/Hermes'):
   process.terminate();process.wait(timeout=15)
 for name in receipt['modified_paths']:
  source=backup/'core'/name;target=root/'hermes-agent'/name
  if source.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
  elif source.with_name(source.name+'.absent').exists():target.unlink(missing_ok=True)
  else:raise ValueError('Incomplete core snapshot: '+name)
 for name in plan['profile']:
  source=backup/'profile'/name;target=root/'data'/name
  if source.exists():shutil.copy2(source,target);target.chmod(0o600)
  elif source.with_name(source.name+'.absent').exists():target.unlink(missing_ok=True)
 plugin=root/'data/plugins/bn-gsd'
 if plugin.exists():
  archive=root/'GSD/disabled-plugin-after-rollback'
  if archive.exists():raise ValueError('Previous rollback plugin archive exists')
  plugin.rename(archive)
 print(json.dumps({**plan,'restored':True,'restart_command':str(root/'bin/hermes-bn-telegram')+' start'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
