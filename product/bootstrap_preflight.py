"""Machine checks before creating any new owner state. No privilege escalation."""
import hashlib
import json
import platform
from pathlib import Path

def compute_pin(bundle):
    bundle=Path(bundle).resolve();root=bundle/'Hermes'
    config=json.loads((bundle/'configuration/memory.template.json').read_text())
    package=Path(config['package_root'].replace('__HERMES_ROOT__',str(root))).resolve()
    if not package.is_relative_to(root/'Memory/releases'):
        raise PermissionError('preflight_memory_root_outside_bundle')
    return json.loads((package/'compute-runtime.json').read_text())


def main():
    B=Path(__file__).resolve().parent
    pin=compute_pin(B)
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


if __name__=='__main__':main()
