"""Offline source gate. No local runtime, credentials or model required."""
from pathlib import Path
import hashlib,json,subprocess,sys,tomllib
R=Path(__file__).resolve().parents[1]
lock=json.loads((R/'locks/product.lock.json').read_text())
from pair_contract import verify_pair
verify_pair(R)
origin=json.loads((R/'locks/source-import.json').read_text())
tracked=set(subprocess.run(['git','ls-files','-z'],cwd=R,capture_output=True,check=True).stdout.decode().split('\0'))
missing=[n for n in origin['files'] if 'product/'+n not in tracked or not (R/'product'/n).is_file()]
if missing:raise SystemExit('Missing committed product source: '+repr(missing[:5]))
for n in tracked:
 p=Path(n)
 if '.operator' in p.parts or p.name in ['auth.json','.env','voyage.key','telegram.token','release_ed25519']:raise SystemExit('Owner authority must not be committed: '+n)
 if n.startswith('product/') and (R/n).is_file() and (R/n).stat().st_size>80*1024*1024:raise SystemExit('Unclassified large program object: '+n)
memory=lock['components']['Memory'];intake=lock['components']['Intake']
if json.loads((R/'product/Hermes/Memory/releases'/memory/'release.json').read_text())['version']!=memory:raise SystemExit('Memory lock mismatch')
if tomllib.loads((R/'product/Intake/pyproject.toml').read_text())['project']['version']!=intake:raise SystemExit('Intake lock mismatch')
print(json.dumps({'committed_product_files':len(origin['files']),'owner_authority_absent':True,'native_execution_claimed':False}))

active_guide=(R/'product/УСТАНОВКА.md').read_text()
if 'INSTALL-UPDATE-RU.md' in active_guide or 'full-20261031 плюс' in active_guide:raise SystemExit('Current full install guide still requires a historical patch layer')
