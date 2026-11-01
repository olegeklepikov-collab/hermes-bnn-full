#!/bin/bash
set -euo pipefail
bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then echo 'Requires native macOS Apple Silicon' >&2; exit 2; fi
if [[ -e "$bundle_root/Hermes/state/bootstrap.json" ]]; then echo 'Profile already initialized. Use verification and service commands; do not reinstall over owner data.' >&2; exit 3; fi
export HERMES_HOME="$bundle_root/Hermes/data" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
base_python="$bundle_root/Hermes/runtime/python/cpython-3.14.6-macos-aarch64-none/bin/python3.14"
"$base_python" -s -S "$bundle_root/verify_bundle.py"
"$base_python" -s -S "$bundle_root/bootstrap_preflight.py"
"$base_python" -s -S "$bundle_root/relocate_install.py"
"$bundle_root/Hermes/hermes-agent/venv/bin/python" "$bundle_root/bootstrap_full.py" initialize
"$bundle_root/Hermes/hermes-agent/venv/bin/python" "$bundle_root/bootstrap_full.py" verify
