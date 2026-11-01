"""Real source Store and worker, observed state and file effects; no fake model success."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
WORK = PACKAGE.parent
BUNDLE = WORK / "work/gsd-bundle"


@pytest.fixture
def host(tmp_path, request):
    settings = json.loads(Path(request.config.getoption("--gsd-settings")).read_text())
    for name in ["state", "operator", "workspace"]:
        (tmp_path / name).mkdir(mode=0o700)
    settings.update(state_dir=str(tmp_path / "state"), operator_dir=str(tmp_path / "operator"),
                    workspace=str(tmp_path / "workspace"), anchor_file=str(tmp_path / "operator/anchor.json"))
    for k in ["store_key", "native_key", "grant_key"]:
        path = tmp_path / "operator" / (k + ".key")
        path.write_bytes(secrets.token_bytes(32)); path.chmod(0o600)
        settings[k] = str(path)
    settings["limits"] = {"tokens": 500, "model_calls": 4, "child_jobs": 3,
        "wall_seconds": 600, "output_tokens":32768, "reserve_tokens": 50, "reserve_calls": 1, "tool_calls": 4}
    path = tmp_path / "operator/settings.json"
    path.write_text(json.dumps(settings)); path.chmod(0o600)
    def call(operation, arguments=None, ok=True):
        response = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "worker.py"), "--settings", str(path)],
            input=json.dumps({"operation": operation, "arguments": arguments or {}}), text=True,
            capture_output=True, timeout=30, env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})
        value = json.loads(response.stdout)
        if ok:
            assert response.returncode == 0, value
            assert value["ok"], value
            return value["result"]
        assert response.returncode != 0 and not value["ok"], value
        return value
    call.path = path
    call.settings = settings
    call.bundle = Path(settings["bundle_root"])
    call("init"); call("session", {"sid": "root", "platform": "cli"})
    return call


def test_shared_concurrent_reservations_unknown_cost_and_completion_reserve(host):
    host("session", {"sid": "child", "platform": "subagent", "parent": "root"})
    def reserve(sid):
        try:
            return host("reserve", {"sid": sid, "request_id": sid, "fingerprint": "f", "upper_tokens": 300})
        except AssertionError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["root", "child"]))
    successful = [r for r in results if r]
    assert len(successful) == 1
    host("settle", {"request_id": successful[0]["id"], "error": True})
    state = host("family_status", {"sid": "root"})["resource"]
    assert state["spent_tokens"] == 300 and state["reserved_tokens"] == 0
    assert state["unknown_usage_reservations"] == 1
    host("reserve", {"sid": "root", "request_id": "excess", "fingerprint": "f", "upper_tokens": 151}, ok=False)
    host("phase", {"sid": "root", "phase": "finalizing"})
    host("reserve", {"sid": "root", "request_id": "final", "fingerprint": "f", "upper_tokens": 200})
    host("settle", {"request_id": "final", "actual_tokens": 10})
    assert host("family_status", {"sid": "child"})["resource"]["spent_tokens"] == 310


def test_stop_resume_and_case_attachment_do_not_refill(host):
    host("reserve", {"sid": "root", "request_id": "one", "fingerprint": "f", "upper_tokens": 100})
    host("settle", {"request_id": "one", "actual_tokens": 40})
    host("bind_case", {"sid": "root", "case_id": "case1"})
    family = host("stop", {"sid": "root", "reason": "test"})["family"]
    host("reserve", {"sid": "root", "request_id": "two", "fingerprint": "f", "upper_tokens": 1}, ok=False)
    host("session", {"sid": "other", "platform": "cli"})
    host("bind_case", {"sid": "other", "case_id": "case1"}, ok=False)
    host("bind_case", {"sid": "other", "case_id": "case1", "allow_join": True})
    assert host("family_status", {"sid": "other"})["resource"]["status"] == "stopped"
    host("operator_resume", {"family_id": family, "reason": "Explicit test recovery"})
    state = host("family_status", {"sid": "other"})["resource"]
    assert state["spent_tokens"] == 40 and state["authorized_calls"] == 1
    host("reserve", {"sid": "root", "request_id": "one", "fingerprint": "f", "upper_tokens": 1}, ok=False)


def test_operator_attachment_preserves_product_identity_and_ownership(host):
    host("bind_case", {"sid": "root", "case_id": "case1"})
    host("session", {"sid": "other", "platform": "cli"})
    registered = host("model_engine", {"sid": "other", "tool": "gsd_product_register", "arguments": {
        "namespace": "synthetic", "logical_key": "one", "product": {"status": "unreviewed", "text": "unit fixture"},
        "input_objects": {}, "origin_component": "G", "origin_ref": "declared_synthetic_fixture",
        "expected_version": 0, "request_id": "one"}})["result"]["product"]
    host("model_engine", {"sid": "root", "tool": "gsd_product_get", "arguments": {"product_id": registered["id"]}}, ok=False)
    host("bind_case", {"sid": "other", "case_id": "case1", "allow_join": True})
    current = host("model_engine", {"sid": "root", "tool": "gsd_product_get", "arguments": {"product_id": registered["id"]}})["result"]["product"]
    assert current == registered and current["status"] == "unreviewed"


def test_tool_admission_budget_is_shared(host):
    host("session", {"sid": "child", "platform": "subagent", "parent": "root"})
    for i in range(4):
        host("tool_call", {"sid": "root" if i % 2 else "child", "name": "read"})
    host("tool_call", {"sid": "root", "name": "read"}, ok=False)


def test_rollback_mismatch_missing_key_and_exact_copy_recovery(host):
    db = Path(host.settings["state_dir"]) / "state.sqlite3"
    snapshot = db.read_bytes()
    host("phase", {"sid": "root", "phase": "working"})
    current = db.read_bytes()
    db.write_bytes(snapshot)
    assert "DEGRADED" in host("family_status", {"sid": "root"}, ok=False)["error"]["message"]
    db.write_bytes(current)
    host("family_status", {"sid": "root"})
    key = Path(host.settings["store_key"]); old = key.read_bytes(); key.unlink()
    host("family_status", {"sid": "root"}, ok=False)
    assert not key.exists()
    key.write_bytes(old); key.chmod(0o600)
    host("family_status", {"sid": "root"})


def test_real_case_isolation_and_model_cannot_admit_postcondition(host):
    fixture = json.loads((host.bundle / "examples/case_create.json").read_text())
    created = host("model_engine", {"sid": "root", "tool": "gsd_case_create", "arguments": fixture})
    run_id = created["result"]["run_id"]
    host("session", {"sid": "other", "platform": "cli"})
    host("model_engine", {"sid": "other", "tool": "gsd_case_get", "arguments": {"run_id": run_id}}, ok=False)
    rejected = host("model_engine", {"sid": "root", "tool": "gsd_case_change", "arguments": {
        "run_id": run_id, "request_id": "forged", "expected_store_revision": 0,
        "operation": "commit", "payload": {"postcondition_observed": True}}})
    assert not rejected["ok"] and rejected["error"]["code"] == "HOST_POSTCONDITION_REVIEW_REQUIRED"
    prepared = host("procedure_inputs", {"sid": "root", "run_id": run_id, "procedure_id": "BOOT.01", "declared_inputs": {}})
    assert prepared["ready"] and not prepared["data_closure_truncated"]
    assert prepared["source_dependency_nodes"]
    assert all(row["collection"] in {"contexts", "sources"} for row in prepared["source_dependency_nodes"].values())
    assert "claims" not in prepared["source_case"]["case"]


def test_real_artifact_denials_and_positive_control(host):
    args = {"name": "proof.txt", "content": "Observed synthetic effect"}
    destination = Path(host.settings["workspace"]) / "artifacts/proof.txt"
    host("artifact", {"sid": "root", "arguments": args, "grant_id": "0" * 32}, ok=False)
    assert not destination.exists()
    grant = host("issue_grant", {"sid": "root", "arguments": args, "ttl": 300, "reason": "synthetic check"})["grant_id"]
    host("artifact", {"sid": "root", "arguments": {**args, "content": "changed"}, "grant_id": grant}, ok=False)
    assert not destination.exists()
    result = host("artifact", {"sid": "root", "arguments": args, "grant_id": grant})
    assert result["created"] and destination.read_text() == args["content"]
    assert result["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    host("artifact", {"sid": "root", "arguments": args, "grant_id": grant}, ok=False)
    assert destination.read_text() == args["content"]


@pytest.mark.parametrize("failure", ["expired", "revoked", "bad_mac", "missing_verifier", "existing_target"])
def test_artifact_failure_preserves_observed_target(host, failure):
    args = {"name": "negative.txt", "content": "forbidden"}
    grant = host("issue_grant", {"sid": "root", "arguments": args, "ttl": 1 if failure == "expired" else 300, "reason": "test"})["grant_id"]
    destination = Path(host.settings["workspace"]) / "artifacts/negative.txt"
    if failure == "expired": time.sleep(1.05)
    if failure == "revoked": host("revoke_grant", {"grant_id": grant, "reason": "withdrawn"})
    if failure == "bad_mac":
        p = Path(host.settings["operator_dir"]) / "grants" / (grant + ".json")
        g = json.loads(p.read_text()); g["mac"] = "0" * 64; p.write_text(json.dumps(g))
    if failure == "missing_verifier": Path(host.settings["grant_key"]).unlink()
    if failure == "existing_target":
        destination.parent.mkdir(mode=0o700); destination.write_text("unchanged")
    host("artifact", {"sid": "root", "arguments": args, "grant_id": grant}, ok=False)
    assert destination.read_text() == "unchanged" if failure == "existing_target" else not destination.exists()


def test_dead_owner_is_not_respawned_and_unsettled_usage_is_preserved(host):
    job = host("job_create", {"sid": "root", "role": "G", "operation": "generation", "inputs": {},
        "request_id": "dead", "owner": {"pid": 99999999, "created_at": 0}})
    host("session", {"sid": "child", "parent": "root", "job_id": job["id"], "platform": "subagent"})
    host("reserve", {"sid": "child", "request_id": "unknown", "fingerprint": "f", "upper_tokens": 100})
    recovery = host("recover_dead")
    assert recovery["interrupted"] == [job["id"]] and not recovery["automatic_respawn"]
    state = host("family_status", {"sid": "root"})["resource"]
    assert state["status"] == "paused" and state["reserved_tokens"] == 100
    host("reserve", {"sid": "child", "request_id": "retry", "fingerprint": "f", "upper_tokens": 1}, ok=False)


def test_partition_covers_complete_source_and_never_splits_mandatory_context(host):
    records = [{"id": str(n), "complete_independent_text": "я" * 300000} for n in range(2)]
    raw = json.dumps(records, ensure_ascii=False).encode()
    path = Path(host.settings["workspace"]) / "large-independent-records.json"; path.write_bytes(raw)
    context = host("engine", {"tool": "gsd_context", "arguments": {"components": "S", "profile": "engineering", "byte_limit": 8388608}})["result"]
    plan = host("prepare_work_file", {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
        "key": "leaf:3C.S06.A", "request_id": "partition", "context_profile": "engineering"})
    limit = 2097152
    assert context["bytes"] + len(raw) > limit  # The unsplit input really exceeds the envelope.
    assert plan["coverage_indices"] == [0, 1] and not plan["truncated"]
    recovered = [op["inputs"]["record"] for op in plan["operations"]]
    assert recovered == records
    assert all(context["bytes"] + len(json.dumps(op["inputs"], ensure_ascii=False).encode()) < limit
               for op in plan["operations"])
    path.write_text("[]")
    host("prepare_work_file", {"path": str(path), "sha256": plan["source_sha256"], "key": "leaf:3C.S06.A", "request_id": "changed"}, ok=False)


def test_scope_mismatch_is_rejected_before_native_job_allocation(host):
    generation = {"id": "g", "task": "synthetic", "product_kind": "hypothesis", "seed": "synthetic",
        "scope": "different", "frame": "alternatives", "constraints": [], "method": "agent", "max_candidates": 4, "scan_budget": 20}
    before = host("family_status", {"sid": "root"})
    failure = host("validate_analysis", {"components": "GSD", "request": {"generation": generation,
        "scope": "scope", "question": "synthetic", "observations": [], "candidates": []}}, ok=False)
    assert "before native launch" in failure["error"]["message"]
    after = host("family_status", {"sid": "root"})
    assert after["jobs"] == before["jobs"] == []
    assert after["resource"]["authorized_calls"] == before["resource"]["authorized_calls"] == 0


def test_scoped_reader_allows_public_file_and_rejects_credentials_before_read(tmp_path):
    sys.path.insert(0, str(PACKAGE))
    from bn_gsd.paths import scoped_public_file
    public = tmp_path / "public.txt"; public.write_text("synthetic public data")
    secret = tmp_path / ".env"; secret.write_text("SYNTHETIC_SECRET=unit_fixture")
    assert scoped_public_file(str(public), [tmp_path]).read_text() == "synthetic public data"
    visited = []
    def read(name):
        path = scoped_public_file(name, [tmp_path]); visited.append(path); return path.read_text()
    with pytest.raises(ValueError): read(str(secret))
    with pytest.raises(ValueError): read("public.txt")
    assert not visited
