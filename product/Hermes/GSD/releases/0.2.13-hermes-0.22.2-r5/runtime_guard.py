#!/usr/bin/env python3
"""Verify an operator-sealed core before startup; no silent compatibility fallback."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import os


def require_profile_binding(home):
    path = Path(home) / "execution-controls.json"
    if path.is_symlink():
        raise ValueError("Unsafe execution-control binding")
    policy = json.loads(path.read_text())
    if type(policy.get("version")) is not int or policy["version"] != 1 or any("bn-gsd" not in policy.get("required", {}).get(k, []) for k in ["tool", "tool_result", "llm", "auxiliary"]):
        raise ValueError("GSD requires all three mandatory execution-control bindings")
    return policy


def verify(core, manifest):
    core, manifest = Path(core).resolve(), Path(manifest)
    expected = json.loads(manifest.read_text())
    if expected["version"] != 1:
        raise ValueError("Unknown core compatibility record")
    for name, sha in expected["files"].items():
        p = (core / name).resolve()
        if not p.is_relative_to(core) or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            raise ValueError("Hermes compatibility/integrity check failed: " + name)
    return expected


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--core", required=True); p.add_argument("--manifest", required=True)
    p.add_argument("args", nargs=argparse.REMAINDER)
    a = p.parse_args(); result = verify(a.core, a.manifest)
    if a.args:
        if not os.environ.get("HERMES_HOME", "").strip():
            raise ValueError("The guarded launcher requires an explicit HERMES_HOME")
        require_profile_binding(os.environ["HERMES_HOME"])
        args = a.args[1:] if a.args[0] == "--" else a.args
        raise SystemExit(subprocess.call([sys.executable, "-m", "hermes_cli.main", *args], cwd=a.core))
    print(json.dumps({"verified": True, "hermes_commit": result["hermes_commit"], "files": len(result["files"])}))
