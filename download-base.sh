#!/bin/bash
# Compatibility entry only: the current release is one complete archive.
set -euo pipefail
bnn_script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$bnn_script_root/download.sh" "$@"
