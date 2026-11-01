#!/bin/bash
HERMES_BNN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HERMES_BNN_ROOT
# Compatibility variable consumed by the existing dedicated Beads wrapper.
export HERMES_BN_ROOT="$HERMES_BNN_ROOT"
export HERMES_HOME="$HERMES_BNN_ROOT/data"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1

# Resolve the isolated checkout before editable packages and inherited environments.
export PYTHONPATH="$HERMES_BNN_ROOT/hermes-agent"

# Bundled native command dependencies; no global package-manager installation.
hermes_bundle_root="$(cd "$HERMES_BNN_ROOT/.." && pwd)"
export PATH="$HERMES_BNN_ROOT/bin:$hermes_bundle_root/NativeEnvironment/opt/homebrew/bin:$HERMES_BNN_ROOT/UDR/software/bin:$PATH"
hermes_native_libraries=""
for hermes_lib_dir in "$hermes_bundle_root"/NativeEnvironment/opt/homebrew/Cellar/*/*/lib; do
  if [[ -d "$hermes_lib_dir" ]]; then hermes_native_libraries="${hermes_native_libraries:+$hermes_native_libraries:}$hermes_lib_dir"; fi
done
export DYLD_LIBRARY_PATH="$hermes_native_libraries${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
