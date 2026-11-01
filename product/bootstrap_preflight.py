"""Machine checks before creating any new owner state. No privilege escalation."""
import hashlib
import json
import platform
from pathlib import Path

B=Path(__file__).resolve().parent
pin=json.loads((B/'Hermes/Memory/releases/2.0.0-dev.45/compute-runtime.json').read_text())
if platform.system()!='Darwin' or platform.machine()!='arm64':raise SystemExit('Requires native macOS Apple Silicon')
if platform.mac_ver()[0]!=pin['os_release']:
    raise SystemExit('Compute isolation is qualified for macOS '+pin['os_release']+'; this OS requires separate qualification before execution')
if hashlib.sha256(Path('/usr/bin/sandbox-exec').read_bytes()).hexdigest()!=pin['sandbox_sha256']:
    raise SystemExit('System sandbox version differs from the qualified runtime; no unsandboxed fallback')
for name,h in json.loads((B/'configuration/external-native-pins.json').read_text()).items():
    path=Path(name)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=h:
        raise SystemExit('Install the supplied qualified native R release before initialization: Installers/R-4.6.1-arm64.pkg; existing frameworks are never overwritten by this script')
print(json.dumps({'machine_preflight':True,'os':platform.mac_ver()[0],'architecture':'arm64','native_R_matches_supplied_release':True,'owner_state_created':False}))
