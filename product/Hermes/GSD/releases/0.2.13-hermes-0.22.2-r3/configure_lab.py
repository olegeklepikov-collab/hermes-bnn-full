#!/usr/bin/env python3
"""Create a fresh isolated host; never modifies the active Hermes BN configuration."""
from pathlib import Path
import json
import os
import secrets
import shutil
import hashlib
import subprocess
import sys
import argparse

parser = argparse.ArgumentParser(description="Prepare a laboratory profile; credentials are never inferred")
parser.add_argument("--auth-store", help="Explicit canonical auth store of the laboratory owner")
arguments = parser.parse_args()

PACKAGE = Path(__file__).resolve().parent
WORK = PACKAGE.parent
HOME = WORK / "lab-home"
CORE = WORK / "work/hermes-agent"
BUNDLE = WORK / "work/gsd-bundle"
PYTHON = CORE / "venv/bin/python"
OP = WORK / "lab-operator"
STATE = WORK / "lab-state"
SPACE = WORK / "lab-workspace"
for p in [HOME, OP, STATE, SPACE]:
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    p.chmod(0o700)
for name in ["store.key", "native.key", "grant.key"]:
    p = OP / name
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
settings = {"bundle_root": str(BUNDLE), "python": str(PYTHON), "state_dir": str(STATE),
            "operator_dir": str(OP), "store_key": str(OP / "store.key"),
            "native_key": str(OP / "native.key"), "grant_key": str(OP / "grant.key"),
            "anchor_file": str(OP / "anchor.json"), "workspace": str(SPACE),
            "provider": "openai-codex", "child_timeout_seconds": 180,
            "integration_manifest_sha256": hashlib.sha256((BUNDLE / "manifest.json").read_bytes()).hexdigest(),
            "engine_manifest_sha256": hashlib.sha256((BUNDLE / "engine/manifest.json").read_bytes()).hexdigest(),
            "limits": {"tokens": 4000000, "model_calls": 64, "child_jobs": 32,
                       "wall_seconds": 7200, "output_tokens": 4096, "request_bytes": 2097152}}
p = OP / "settings.json"
if p.exists() and json.loads(p.read_text()) != settings:
    raise SystemExit("Existing lab settings differ; do not reset its resource accounting")
p.write_text(json.dumps(settings, indent=2));p.chmod(0o600)
plugin = HOME / "plugins/bn-gsd"
if plugin.exists():
    shutil.rmtree(plugin)
shutil.copytree(PACKAGE / "plugin", plugin)
sys.path.insert(0, str(CORE))
from hermes_cli.config import atomic_config_write
config = {"model": {"provider": "openai-codex", "default": "gpt-6.1-sol"},
          "plugins": {"enabled": ["bn-gsd"], "hook_callback_timeout": 15,
                      "entries": {"bn-gsd": {"enabled": True, "settings": {
                          "package_root": str(PACKAGE), "settings_file": str(p)}}}},
          "terminal": {"backend": "local", "cwd": str(SPACE)},
          "compression": {"enabled": False}, "curator": {"enabled": False},
          "memory": {"memory_enabled": False, "user_profile_enabled": False},
          "delegation": {"max_concurrent_children": 2, "child_timeout_seconds": 180,
                         "orchestrator_enabled": False},
          "mcp_servers": {}, "agent": {"max_turns": 12}}
atomic_config_write(HOME / "config.yaml", config)
# Deliberately share the existing owner's canonical auth store; do not fork rotating grants.
auth = HOME / "auth.json"
if not auth.exists() and arguments.auth_store:
    auth.symlink_to(Path(arguments.auth_store).expanduser().resolve(strict=True))
env = os.environ.copy()
env.update(HERMES_HOME=str(HOME), PYTHONDONTWRITEBYTECODE="1")
if not (STATE / "state.sqlite3").exists():
    subprocess.run([str(PYTHON), "-I", "-B", str(PACKAGE / "worker.py"), "--settings", str(p)],
                   input='{"operation":"init","arguments":{}}', text=True, env=env, check=True)
(HOME / "execution-controls.json").write_text(json.dumps({"version": 1,
    "required": {k: ["bn-gsd"] for k in ["tool", "llm", "auxiliary"]}, "timeout_seconds": 15}))
(HOME / "execution-controls.json").chmod(0o600)
print("Isolated GSD host configured; no live gateway was started")
