#!/usr/bin/env python3
"""Cancel one genuine native child via the real local gateway; no external recipient."""
from pathlib import Path
import json
import time
import urllib.request
import urllib.error
import argparse
from bn_gsd.bridge import Bridge

WORK = Path(__file__).resolve().parent.parent
home = WORK / "lab-home"
port = json.loads((WORK / "lab-operator/gateway-test.json").read_text())["port"]
key = next(x.split("=", 1)[1] for x in (home / ".env").read_text().splitlines() if x.startswith("API_SERVER_KEY="))
bridge = Bridge(WORK / "lab-operator/settings.json")
parser = argparse.ArgumentParser(); parser.add_argument("--trial-id", default="v1")
trial_id = parser.parse_args().trial_id
if not trial_id.isalnum(): raise ValueError("Use an alphanumeric immutable trial ID")
sid = "bn-cancel-actual-" + trial_id
operation = {"key": "leaf:3C.S06.A", "inputs": {"claim": "10 метров равно 100 сантиметрам", "primary": "1 m = 100 cm"},
             "request_id": "cancel-native-job-1", "context_profile": "engineering"}
body = {"session_id": sid, "input": "Синтетическая проверка отмены. Выполни ровно один gsd_work; не повторяй при остановке.\n" + json.dumps(operation, ensure_ascii=False)}


def request(path, data=None, idempotent=False):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if idempotent: headers["Idempotency-Key"] = "bn-cancel-create-actual-" + trial_id
    req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
        data=json.dumps(data).encode() if data is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), json.loads(e.read())


status, headers, started = request("/v1/runs", body, True)
assert status == 202, started
run = started["run_id"]
status2, headers2, repeated = request("/v1/runs", body, True)
assert status2 == 202 and repeated["run_id"] == run and headers2.get("Idempotency-Replayed") == "true"
conflict_status, _, conflict = request("/v1/runs", {**body, "input": "different"}, True)
assert conflict_status == 409
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    try:
        state = bridge.call("family_status", {"sid": sid})
        if any(j.get("child_session_id") for j in state["jobs"]): break
    except ValueError:
        pass
    time.sleep(2)
else:
    request("/v1/runs/" + run + "/stop", {})
    raise RuntimeError("No actual native child started; cancellation acceptance not demonstrated")
before = state
stop_status, _, stopped = request("/v1/runs/" + run + "/stop", {})
assert stop_status == 200, stopped
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    _, _, current = request("/v1/runs/" + run)
    if current["status"] in {"cancelled", "interrupted", "failed", "completed"}: break
    time.sleep(2)
after = bridge.call("family_status", {"sid": sid})
jobs = [bridge.call("job_get", {"job_id": j["id"]}) for j in after["jobs"]]
result = {"run_id": run, "duplicate_creation_returned_same_run": True, "conflicting_payload_http_status": conflict_status,
          "stop_response": stopped, "terminal_gateway_status": current["status"],
          "before": before, "after": after, "jobs": jobs}
(WORK / ("results/gateway-cancellation-" + trial_id + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({"gateway_status": current["status"], "family_status": after["resource"]["status"],
                  "job_states": [j["status"] for j in jobs], "child_started": True}, ensure_ascii=False))
