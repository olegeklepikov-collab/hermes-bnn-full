#!/bin/bash
HERMES_BNN_DOLT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$HERMES_BNN_DOLT_ROOT/environment.sh"
export DOLT_ROOT_PATH="$HERMES_BN_ROOT/Dolt/local-state"
unset DOLT_REMOTE_USER DOLT_REMOTE_PASSWORD DOLT_CREDS_ID DOLT_CLI_PASSWORD
export NO_COLOR=1
cd "$HERMES_BN_ROOT/Dolt/databases"
