#!/usr/bin/env python3
"""Restore only installer-owned configuration; retain accounting, keys and unknown outcomes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sys
import psutil


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--home", required=True); p.add_argument("--snapshot", required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(); home, snapshot = Path(a.home).resolve(), Path(a.snapshot).resolve()
    receipt = json.loads((snapshot / "installation.json").read_text())
    if receipt["version"] != 1 or Path(receipt["home"]).resolve() != home:
        raise ValueError("Snapshot belongs to another installation")
    for name, sha in receipt["installed_files"].items():
        if hashlib.sha256((home / name).read_bytes()).hexdigest() != sha:
            raise ValueError("Configuration changed since installation; merge explicitly instead of overwriting: " + name)
    live = []
    for process in psutil.process_iter(["pid", "uids", "cmdline"]):
        if process.pid == os.getpid() or (process.info.get("uids") and process.info["uids"].real != os.getuid()):
            continue
        command = " ".join(process.info.get("cmdline") or [])
        if not any(x in command for x in ["hermes_cli", "run_agent", "cli.py", "tui_gateway"]):
            continue
        try:
            profile = process.environ().get("HERMES_HOME")
            if profile and Path(profile).resolve() == home: live.append(process.pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            raise ValueError("Cannot confirm that a potentially owning Hermes process is stopped")
    if live:
        raise ValueError("Stop this profile before rollback; running PIDs: " + repr(live))
    result = {"apply": a.apply, "home": str(home), "snapshot": str(snapshot),
              "state_and_keys_preserved": True, "resource_reset": False}
    if a.apply:
        for name in receipt["installed_files"]:
            if (snapshot / (name + ".absent")).exists():
                (home / name).unlink()
            else:
                shutil.copy2(snapshot / name, home / name)
        plugin = home / "plugins/bn-gsd"
        if plugin.exists(): shutil.rmtree(plugin)
        if (snapshot / "plugin").exists(): shutil.copytree(snapshot / "plugin", plugin)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
