"""Isolated contract fixtures; no model execution or semantic acceptance claimed."""
from datetime import datetime, timezone
import json
from test_host_contracts import host


def completed_fixture(host):
    data = {"generation": {"id": "fixture"}, "construction_observations": [], "seed_origin": "unattested_input_unless_explicitly_bound"}
    job = host("job_create", {"sid": "root", "role": "G", "operation": "generation", "inputs": data, "request_id": "fixture"})
    job = host("finish_job", {"job_id": job["id"], "status": "completed", "result": {"candidates": [{"synthetic_fixture": True}]},
        "native_receipt": {"terminal_state": "SUCCEEDED", "result_hash": "fixture-only-not-real-executor"}})
    return job, data


def test_null_family_deadline_has_stable_finite_transfer_lease(host):
    host.settings["limits"]["budget_mode"] = "observe"
    host.path.write_text(json.dumps(host.settings))
    host("operator_observation_mode", {"reason": "isolated regression fixture"})
    job, _ = completed_fixture(host)
    args = {"job_id": job["id"], "receiver": "S", "profile": "Standard", "scope": "synthetic regression"}
    a = host("native_handoff", args)
    assert datetime.fromisoformat(a["message"]["deadline"]) > datetime.now(timezone.utc)
    b = host("native_handoff", args)
    assert a["message"] == b["message"] and b["durable_duplicate"]
    state = host("family_status", {"sid": "root"})["resource"]
    assert state["deadline"] is None and state["handoff_units"] == 1


def test_recovery_matches_original_family_inputs_and_receipt(host):
    host.settings["limits"]["budget_mode"] = "observe"
    host.path.write_text(json.dumps(host.settings))
    host("operator_observation_mode", {"reason": "isolated regression fixture"})
    job, data = completed_fixture(host)
    assert host("resume_generation", {"sid": "root", "job_id": job["id"], "inputs": data}) == job
    host("resume_generation", {"sid": "root", "job_id": job["id"], "inputs": {}}, ok=False)
    host("session", {"sid": "foreign", "platform": "cli"})
    host("resume_generation", {"sid": "foreign", "job_id": job["id"], "inputs": data}, ok=False)
    assert host("family_status", {"sid": "root"})["resource"]["jobs_started"] == 1


def test_finite_family_deadline_is_preserved(host):
    job, _ = completed_fixture(host)
    deadline = host("family_status", {"sid": "root"})["resource"]["deadline"]
    packet = host("native_handoff", {"job_id": job["id"], "receiver": "S", "profile": "Standard", "scope": "finite regression"})
    assert abs(datetime.fromisoformat(packet["message"]["deadline"]).timestamp() - deadline) < 0.00001
