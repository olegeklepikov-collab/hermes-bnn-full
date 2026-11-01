#!/usr/bin/env python3
"""Preview/apply a scoped installation. Existing credentials and source code are never overwritten."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import shlex
from datetime import datetime, timezone

PACKAGE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    for field in ["home", "core", "bundle", "operator", "state", "workspace"]:
        p.add_argument("--" + field, required=True)
    p.add_argument("--provider", default="openai-codex")
    p.add_argument("--model", default="gpt-6.1-sol")
    p.add_argument("--core-manifest", default=str(PACKAGE / "release/core-manifest.json"))
    p.add_argument("--auth-store", help="Optional existing owner's canonical auth store; no credential copying")
    p.add_argument("--runtime-root")
    p.add_argument("--r-runtime")
    p.add_argument("--tool-policy",default=str(PACKAGE / "release/tool-policy.json"))
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    paths = {k: Path(getattr(a, k)).expanduser().resolve() for k in ["home", "core", "bundle", "operator", "state", "workspace"]}
    home, core, bundle, operator, state, workspace = (paths[k] for k in ["home", "core", "bundle", "operator", "state", "workspace"])
    from runtime_guard import verify
    verify(core, a.core_manifest)
    if operator.is_relative_to(state) or operator.is_relative_to(workspace) or state.is_relative_to(workspace) or home.is_relative_to(workspace):
        raise ValueError("Operator keys, state and ordinary workspace must be separated")
    plan = {"paths": {k: str(v) for k, v in paths.items()}, "active_source_modified": False,
            "mandatory_controls": ["tool", "tool_result", "llm", "auxiliary"], "mode": "operational_with_scoped_executors",
            "legacy_unadapted_executors": "explicit_catalogue_with_OS_sandbox", "credential_copy": False, "apply": a.apply}
    if not a.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2)); return
    python = core / (".venv/bin/python" if (core / ".venv/bin/python").exists() else "venv/bin/python")
    sys.path.insert(0, str(core))
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    for path in [home, operator, state, workspace]:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    operator.chmod(0o700); state.chmod(0o700)
    snapshot = operator / "install-snapshots" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot.mkdir(mode=0o700, parents=True)
    for name in ["config.yaml", "execution-controls.json", "runtime-manager.json"]:
        path = home / name
        if path.exists(): shutil.copy2(path, snapshot / name)
        else: (snapshot / (name + ".absent")).touch(mode=0o600)
    for name in ["store.key", "native.key", "grant.key"]:
        key = operator / name
        if not key.exists():
            key.write_bytes(secrets.token_bytes(32)); key.chmod(0o600)
    settings = {"bundle_root": str(bundle), "python": str(python), "state_dir": str(state), "operator_dir": str(operator),
        "store_key": str(operator / "store.key"), "native_key": str(operator / "native.key"),
        "grant_key": str(operator / "grant.key"), "anchor_file": str(operator / "anchor.json"),
        "workspace": str(workspace), "provider": a.provider,
        "runtime_root":str(Path(a.runtime_root or core.parent).resolve()),
        "r_runtime":str(Path(a.r_runtime or Path(a.runtime_root or core.parent).parent / "hermes-bn-r").resolve()), "child_timeout_seconds": 180,
        "integration_manifest_sha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest(),
        "engine_manifest_sha256": hashlib.sha256((bundle / "engine/manifest.json").read_bytes()).hexdigest(),
        "limits": {"tokens": 4000000, "model_calls": 64, "child_jobs": 32,
                   "wall_seconds": 7200, "output_tokens": 32768, "request_bytes": 2097152}}
    settings_file = operator / "settings.json"

    plugin = home / "plugins/bn-gsd"
    if plugin.exists(): shutil.copytree(plugin, snapshot / "plugin")
    if plugin.exists(): shutil.rmtree(plugin)
    shutil.copytree(PACKAGE / "plugin", plugin)
    config_path = home / "config.yaml"
    config = read_user_config_raw(config_path) if config_path.exists() else {}
    config = config or {}
    config.setdefault("model", {"provider": a.provider, "default": a.model})
    config.setdefault("compression", {})["enabled"] = False
    # Preserve the instant derived title; this installed Codex model rejects the
    # title helper's forced reasoning=none. It must not create unbounded idle calls.
    config.setdefault("auxiliary", {}).setdefault("title_generation", {})["model_upgrade_enabled"] = False
    plugins = config.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if "bn-gsd" not in enabled: enabled.append("bn-gsd")
    plugins["hook_callback_timeout"] = 15
    plugins.setdefault("entries", {})["bn-gsd"] = {"enabled": True, "settings": {
        "package_root": str(PACKAGE), "settings_file": str(settings_file), "core_manifest": str(Path(a.core_manifest).resolve())}}
    from hermes_cli.tools_config import _platform_default_toolset
    platform_toolsets=config.setdefault("platform_toolsets",{})
    for platform in ["cli","gui","api_server","telegram","tui","cron"]:
        old=platform_toolsets.get(platform)
        selected=old if isinstance(old,list) else [_platform_default_toolset(platform)]
        platform_toolsets[platform]=sorted(set(selected)|set(config.get("mcp_servers",{}))|{"gsd_native","gsd_integration","skills"})
    config.setdefault("agent",{})["coding_context"]="auto"
    config["execution_controls_required"]=True
    config.setdefault("terminal", {})["backend"]="bn_guarded_local"
    servers=config.get("mcp_servers",{})
    if "rstats" in servers:
        servers["rstats"]["command"]=str(python)
        servers["rstats"]["args"]=[str(PACKAGE / "sandbox_mcp.py"),"--settings",str(settings_file)]
    from bn_gsd.tool_policy import transport_digest
    policy=Path(a.tool_policy).resolve()
    settings.update(tool_policy=str(policy),tool_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
        mcp_transport_digests={n:transport_digest(v) for n,v in servers.items()})
    root=Path(settings["runtime_root"])
    code={}
    for directory in ["ASReview","AlphaXiv","Beads","Dolt","Consensus","Crossref","Exa","Firecrawl","Keenable","Nimble","OpenAlex","Parallel","Pendar","PubMed","R","RussianResearch","ScholarSidekick","Scite","SemanticScholar","Tavily","Undermind","WebOfScience","Wolfram","Zotero"]:
        source=root/directory
        for pattern in ["*.py","*.sh","scripts/*.R","bin/*"]:
            for path in source.glob(pattern):
                if path.is_file() and not path.is_symlink() and path.stat().st_size<1000000:
                    code[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
    settings["local_adapter_sha256"]=code
    if settings_file.exists():
        old=json.loads(settings_file.read_text())
        for name in ["state_dir","operator_dir","workspace","limits"]:
            if old.get(name)!=settings.get(name):raise ValueError("Accounting scope differs; no silent reset")
    external_policy=operator/"external-host-policy.json"
    if not external_policy.exists():
        external_policy.write_text(json.dumps({"contract":"gsd.host-policy/1","procedure_executors":{"Hermes-native-external":{
            "enabled":True,"components":["G","S","D"],"key_file":str(operator/"native.key")}}},indent=2));external_policy.chmod(0o600)
    settings_file.write_text(json.dumps(settings,indent=2));settings_file.chmod(0o600)
    atomic_config_write(config_path, config)
    controls_path = home / "execution-controls.json"
    controls = json.loads(controls_path.read_text()) if controls_path.exists() else {"version": 1, "required": {}, "timeout_seconds": 15}
    for kind in ["tool", "tool_result", "llm", "auxiliary"]:
        required = controls["required"].setdefault(kind, [])
        if "bn-gsd" not in required: required.append("bn-gsd")
    controls_path.write_text(json.dumps(controls, indent=2)); controls_path.chmod(0o600)
    manager = {"version": 1, "execution_policy_required": True, "manager": "Hermes BN GSD", "update_command": shlex.join([str(python), str(PACKAGE / "stage_update.py"), "--help"])}
    (home / "runtime-manager.json").write_text(json.dumps(manager, indent=2)); (home / "runtime-manager.json").chmod(0o600)
    if a.auth_store and not (home / "auth.json").exists():
        (home / "auth.json").symlink_to(Path(a.auth_store).resolve(strict=True))
    if not (state / "state.sqlite3").exists():
        from tools.environments.local import served_profile_child_env
        env = served_profile_child_env(target_home=home, inherit_credentials=False)
        subprocess.run([str(python), "-I", "-B", str(PACKAGE / "worker.py"), "--settings", str(settings_file)],
            input='{"operation":"init","arguments":{}}', text=True, env=env, check=True)
    receipt = {"version": 1, "home": str(home), "state_preserved_on_rollback": str(state),
        "installed_files": {name: hashlib.sha256((home / name).read_bytes()).hexdigest()
                            for name in ["config.yaml", "execution-controls.json", "runtime-manager.json"]}}
    (snapshot / "installation.json").write_text(json.dumps(receipt, indent=2)); (snapshot / "installation.json").chmod(0o600)
    print(json.dumps({**plan, "snapshot": str(snapshot), "restart_required": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
