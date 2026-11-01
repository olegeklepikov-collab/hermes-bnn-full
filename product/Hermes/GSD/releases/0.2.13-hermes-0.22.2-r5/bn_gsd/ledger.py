"""Host accounting in the original signed Store; no duplicate GSD case controller."""
from pathlib import Path
import time
import uuid
from .codec import digest


class HostLedger:
    RECORD = "BN.HOST.RUNTIME"

    def __init__(self, store, limits):
        self.store, self.limits = store, limits

    def mutate(self, function):
        with self.store.transaction() as con:
            try:
                revision, state = self.store.get(con, self.RECORD)
            except ValueError as exc:
                if getattr(exc, "code", None) != "NOT_FOUND":
                    raise
                revision, state = 0, {"schema": 1, "sessions": {}, "families": {}, "jobs": {},
                                      "requests": {}, "deliveries": {}, "events": []}
            result = function(state)
            self.store.put(con, self.RECORD, state, revision + 1)
            return result

    def read(self, function):
        with self.store.transaction() as con:
            _, state = self.store.get(con, self.RECORD)
            return function(state)

    def session(self, sid, platform, parent=None, job_id=None, managed_task=None):
        if not sid:
            raise ValueError("A native session identity is required")
        def change(s):
            if sid in s["sessions"]:
                existing=s["sessions"][sid]
                if managed_task and existing.get("managed_task")!=managed_task:raise ValueError("Managed child identity changed")
                return existing
            if parent:
                p = s["sessions"].get(parent)
                if not p:
                    raise ValueError("Unknown native parent")
                family = p["family"]
            else:
                if platform == "subagent":
                    raise ValueError("Unbound native child")
                family = "F." + digest([sid])[:24]
                s["families"][family] = {"status": "running", "limits": dict(self.limits),
                    "deadline": None if self.limits["wall_seconds"] is None else time.time() + self.limits["wall_seconds"], "spent_tokens": 0,
                    "reserved_tokens": 0, "authorized_calls": 0, "jobs_started": 0,
                    "actual_usage_known": 0, "unknown_usage_reservations": 0}
            if managed_task:
                if not parent or platform!="subagent" or job_id:raise ValueError("Managed child requires a native parent")
                f=s["families"][family];self._running(f)
                maximum=f["limits"].get("child_jobs")
                if maximum is not None and f["jobs_started"]>=maximum:raise ValueError("Shared child budget exhausted")
                f["jobs_started"]+=1
            item = {"family": family, "platform": platform, "parent": parent, "job_id": job_id}
            if managed_task:item["managed_task"]=managed_task
            s["sessions"][sid] = item
            if job_id:
                job = s["jobs"][job_id]
                if job["parent_session_id"] != parent or job.get("child_session_id"):
                    raise ValueError("Child binding does not match its pending job")
                job["child_session_id"] = sid
                job["status"] = "running"
            return item
        return self.mutate(change)

    def lookup(self, sid):
        def read(s):
            session = s["sessions"].get(sid)
            if not session:
                raise ValueError("Native lifecycle did not bind this session")
            return {"session": session, "family": s["families"][session["family"]],
                    "job": s["jobs"].get(session.get("job_id"))}
        return self.read(read)

    def create_job(self, sid, role, operation, context_ref, inputs_ref, input_digest, request_id, owner=None,corpus_id=None):
        if role not in "GSD" or len(role) != 1:
            raise ValueError("Invalid semantic role")
        def change(s):
            session = s["sessions"][sid]
            family = s["families"][session["family"]]
            self._running(family)
            job_id = "J." + digest([session["family"], request_id])[:32]
            fp = digest([role, operation, context_ref, input_digest])
            if job_id in s["jobs"]:
                old = s["jobs"][job_id]
                if old["fingerprint"] != fp:
                    raise ValueError("Conflicting job request identity")
                raise ValueError("A job already exists; inspect it, do not re-run automatically")
            if family["limits"]["child_jobs"] is not None and family["jobs_started"] >= family["limits"]["child_jobs"]:
                raise ValueError("Shared child-task budget exhausted")
            family["jobs_started"] += 1
            job = {"id": job_id, "family": session["family"], "parent_session_id": sid,
                   "product_namespace": "NATIVE." + session["family"],
                   "role": role, "operation": operation, "context_ref": context_ref,
                   "inputs_ref": inputs_ref, "input_digest": input_digest, "fingerprint": fp,
                   "status": "pending", "allowed_effects": ["local_analysis"],
                   "created_at": time.time(), "result": None, "owner": owner}
            if corpus_id:job['corpus_id']=corpus_id
            s["jobs"][job_id] = job
            return job
        return self.mutate(change)

    def get_job(self, job_id):
        return self.read(lambda s: s["jobs"][job_id])

    def family_status(self, sid):
        def read(s):
            family = s["sessions"][sid]["family"]
            resource = {**s["families"][family],
                "unsettled_provider_attempts": sum(r["family"] == family and r["state"] == "reserved"
                                                  for r in s["requests"].values()),
                "unknown_usage_accounted_attempts": s["families"][family]["unknown_usage_reservations"]}
            return {"family_id": family, "resource": resource,
                    "jobs": [{k: j.get(k) for k in ["id", "role", "status", "child_session_id", "operation"]}
                             for j in s["jobs"].values() if j["family"] == family]}
        return self.read(read)

    def finish_job(self, job_id, status, result, native_receipt):
        if status not in {"completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("Explicit terminal/unknown job status is required")
        def change(s):
            job = s["jobs"][job_id]
            if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                if digest([job["result"], job["native_receipt"]]) != digest([result, native_receipt]):
                    raise ValueError("Terminal job result is immutable")
                return job
            job.update(status=status, result=result, native_receipt=native_receipt, completed_at=time.time())
            if status == "interrupted" and s["families"][job["family"]]["status"] == "running":
                s["families"][job["family"]]["status"] = "paused"
            return job
        return self.mutate(change)

    @staticmethod
    def _running(family):
        if family["status"] != "running":
            raise ValueError("Run is stopped or requires recovery")
        if family["deadline"] is not None and time.time() > family["deadline"]:
            raise ValueError("Shared wall-clock deadline expired")

    def reserve(self, sid, request_id, fingerprint, upper_tokens, delivery=None, owner=None, logical_id=None,expires_at=None):
        if type(upper_tokens) is not int or upper_tokens <= 0 or not request_id:
            raise ValueError("Invalid provider reservation")
        def change(s):
            if expires_at is not None and (not isinstance(expires_at,(int,float)) or time.time()>=expires_at):
                raise ValueError('Execution admission expired before reservation')
            session = s["sessions"][sid]
            family = s["families"][session["family"]]
            self._running(family)
            if session.get("job_id"):
                calls = sum(r["session_id"] == sid for r in s["requests"].values())
                if family["limits"].get("role_model_calls", 2) is not None and calls >= family["limits"].get("role_model_calls", 2):
                    raise ValueError("Bounded native role call budget exhausted; no recursive orchestration")
            if request_id in s["requests"]:
                raise ValueError("Physical provider request was already reserved; automatic repetition is forbidden")
            if any(r["session_id"] == sid and r["state"] == "reserved" for r in s["requests"].values()):
                raise ValueError("Previous provider outcome/usage has not been settled")
            limits = family["limits"]
            finalizing = session.get("phase") == "finalizing" and not session.get("job_id")
            call_limit = None if limits["model_calls"] is None else limits["model_calls"] - (0 if finalizing else limits.get("reserve_calls", 1))
            token_limit = None if limits["tokens"] is None else limits["tokens"] - (0 if finalizing else limits.get("reserve_tokens", 131072))
            if call_limit is not None and family["authorized_calls"] >= call_limit:
                raise ValueError("Shared model-call budget exhausted")
            if token_limit is not None and family["spent_tokens"] + family["reserved_tokens"] + upper_tokens > token_limit:
                raise ValueError("Shared token budget cannot cover the full reservation")
            family["reserved_tokens"] += upper_tokens
            family["authorized_calls"] += 1
            item = {"id": request_id, "family": session["family"], "session_id": sid,
                    "fingerprint": fingerprint, "logical_id": logical_id or request_id, "upper_tokens": upper_tokens,
                    "state": "reserved", "created_at": time.time(), "owner": owner}
            if delivery:
                if not session.get("job_id"):
                    raise ValueError("Context delivery is not attached to a native job")
                item["context_delivery"] = delivery
                s["jobs"][session["job_id"]].setdefault("deliveries", []).append({
                    "api_request_id": request_id, "request_fingerprint": fingerprint, **delivery})
            s["requests"][request_id] = item
            return item
        return self.mutate(change)

    def operator_observation_mode(self, reason):
        if self.limits.get("budget_mode")!="observe" or not isinstance(reason,str) or not reason.strip():
            raise ValueError("Observation mode requires explicit operator configuration and reason")
        def change(s):
            updated=[]
            for fid,family in s["families"].items():
                before=dict(family["limits"]);old_deadline=family["deadline"]
                family["limits"].update({k:None for k in ["tokens","model_calls","child_jobs","wall_seconds","tool_calls","role_model_calls"]})
                family["limits"].update(budget_mode="observe",output_tokens=self.limits["output_tokens"])
                family["deadline"]=None
                s["events"].append({"event":"operator_observation_mode","family":fid,"before_limits":before,"before_deadline":old_deadline,"reason":reason,"time":time.time()})
                updated.append(fid)
            return {"families_updated":updated,"budget_limits_enforced":False,"accounting_reset":False,"completed_jobs_replayed":False}
        return self.mutate(change)

    def operator_request_limit(self, sid, maximum, reason):
        if type(maximum) is not int or not 0 < maximum <= self.limits["request_bytes"] or not isinstance(reason,str) or not reason.strip():
            raise ValueError("Invalid operator request-window adjustment")
        def change(s):
            fid=s["sessions"][sid]["family"];family=s["families"][fid]
            self._running(family)
            if family["reserved_tokens"] or any(j["family"]==fid and j["status"] in {"pending","running"} for j in s["jobs"].values()):
                raise ValueError("Request window cannot change during an unresolved attempt or child job")
            old=family["limits"].get("request_bytes",self.limits["request_bytes"]);family["limits"]["request_bytes"]=maximum
            s["events"].append({"event":"operator_request_window","family":fid,"before":old,"after":maximum,"reason":reason,"time":time.time()})
            return {"family":fid,"before":old,"after":maximum,"shared_budget_reset":False,"completed_jobs_replayed":False}
        return self.mutate(change)

    def operator_output_limit(self, sid, maximum, reason):
        if type(maximum) is not int or not 0 < maximum <= self.limits["output_tokens"] or not isinstance(reason,str) or not reason.strip():
            raise ValueError("Invalid operator output-window adjustment")
        def change(s):
            fid=s["sessions"][sid]["family"];family=s["families"][fid]
            self._running(family)
            if family["reserved_tokens"] or any(j["family"]==fid and j["status"] in {"pending","running"} for j in s["jobs"].values()):
                raise ValueError("Output window cannot change during an unresolved attempt or child job")
            old=family["limits"]["output_tokens"];family["limits"]["output_tokens"]=maximum
            s["events"].append({"event":"operator_output_window","family":fid,"before":old,"after":maximum,"reason":reason,"time":time.time()})
            return {"family":fid,"before":old,"after":maximum,"shared_budget_reset":False,"completed_jobs_replayed":False}
        return self.mutate(change)

    def settle(self, request_id, actual_tokens=None, error=False):
        def change(s):
            item = s["requests"].get(request_id)
            if item is None:
                return {"settled": False, "reason": "no_authorized_provider_attempt"}
            if item["state"] != "reserved":
                return {"settled": True, "duplicate": True}
            family = s["families"][item["family"]]
            known = type(actual_tokens) is int and actual_tokens >= 0
            charged = actual_tokens if known else item["upper_tokens"]
            family["reserved_tokens"] -= item["upper_tokens"]
            family["spent_tokens"] += charged
            family["actual_usage_known"] += int(known)
            family["unknown_usage_reservations"] += int(not known)
            if charged > item["upper_tokens"]:
                family["status"] = "degraded"
            item.update(state="failed_unknown_cost" if error and not known else "settled",
                        actual_tokens=actual_tokens if known else None, accounted_upper_bound=charged,
                        completed_at=time.time())
            return item
        return self.mutate(change)

    def stop(self, sid, reason):
        def change(s):
            family_id = s["sessions"][sid]["family"]
            s["families"][family_id].update(status="stopped", stop_reason=reason)
            return {"family": family_id, "status": "stopped", "jobs": [j["id"] for j in s["jobs"].values()
                    if j["family"] == family_id and j["status"] in {"pending", "running"}]}
        return self.mutate(change)

    def phase(self, sid, phase):
        if phase not in {"working", "finalizing"}:
            raise ValueError("Invalid host phase")
        return self.mutate(lambda s: s["sessions"][sid].update(phase=phase) or {"phase": phase})

    def bind_case(self, sid, case_id, allow_join=False):
        def change(s):
            mapping = s.setdefault("case_families", {})
            origin = s["sessions"][sid]["family"]
            target = mapping.setdefault(case_id, origin)
            if origin == target:
                return {"family": target, "budget_reset": False}
            if not allow_join:
                raise ValueError("Case belongs to another family; an operator must attach this session")
            a, b = s["families"][origin], s["families"][target]
            if b["limits"]["tokens"] is not None and b["spent_tokens"] + b["reserved_tokens"] + a["spent_tokens"] + a["reserved_tokens"] > b["limits"]["tokens"]:
                raise ValueError("Existing case cannot absorb a fresh session; no budget refill")
            if (b["limits"]["model_calls"] is not None and a["authorized_calls"] + b["authorized_calls"] > b["limits"]["model_calls"]) or (b["limits"]["child_jobs"] is not None and a["jobs_started"] + b["jobs_started"] > b["limits"]["child_jobs"]):
                raise ValueError("Attachment exceeds the existing family's call/job budget")
            for key in ["spent_tokens", "reserved_tokens", "authorized_calls", "jobs_started", "actual_usage_known", "unknown_usage_reservations"]:
                b[key] += a[key]
            for record in [*s["sessions"].values(), *s["jobs"].values(), *s["requests"].values()]:
                if record["family"] == origin:
                    if record.get("id", "").startswith("J."):
                        record.setdefault("product_namespace", "NATIVE." + origin)
                    record["family"] = target
            for key, value in list(mapping.items()):
                if value == origin:
                    mapping[key] = target
            a.update(status="merged", merged_into=target)
            return {"family": target, "budget_reset": False}
        return self.mutate(change)

    def own_product(self, sid, namespace):
        import re
        match = re.match(r"(?:NATIVE\.)?(F\.[0-9a-f]{24})(?:\.|$)", namespace)
        if not match:
            raise ValueError("Product has no native ownership binding")
        def read(s):
            target = s["sessions"][sid]["family"]
            current, seen = match.group(1), set()
            while current != target:
                if current in seen:
                    raise ValueError("Invalid ownership alias cycle")
                seen.add(current)
                current = s["families"].get(current, {}).get("merged_into")
                if not current:
                    raise ValueError("Product belongs to another native family")
            return True
        return self.read(read)

    def own_case(self, sid, case_id):
        def read(s):
            if s.get("case_families", {}).get(case_id) != s["sessions"][sid]["family"]:
                raise ValueError("Case is not attached to this native family")
            return True
        return self.read(read)

    def tool_call(self, sid, name):
        def change(s):
            family = s["families"][s["sessions"][sid]["family"]]
            self._running(family)
            if family["limits"].get("tool_calls",256) is not None and family.get("tool_calls", 0) >= family["limits"].get("tool_calls", 256):
                raise ValueError("Shared tool-call budget exhausted")
            family["tool_calls"] = family.get("tool_calls", 0) + 1
            return {"authorized": True, "tool_calls": family["tool_calls"], "tool": name}
        return self.mutate(change)

    def consume_grant(self, sid, grant_id):
        def change(s):
            self._running(s["families"][s["sessions"][sid]["family"]])
            grants = s.setdefault("grants", {})
            if grant_id in grants:
                raise ValueError("Grant was used or revoked; uncertain effects are not repeated")
            grants[grant_id] = {"state": "used_outcome_unknown", "family": s["sessions"][sid]["family"]}
            return grants[grant_id]
        return self.mutate(change)

    def grant_result(self, grant_id, result):
        return self.mutate(lambda s: s["grants"][grant_id].update(state="completed", result=result) or result)

    def revoke_grant(self, grant_id, reason):
        def change(s):
            grants = s.setdefault("grants", {})
            if grant_id in grants and grants[grant_id]["state"] != "revoked":
                raise ValueError("Used grant cannot be undone by revocation")
            grants[grant_id] = {"state": "revoked", "reason": reason}
            return grants[grant_id]
        return self.mutate(change)

    def recover_dead_owners(self):
        import psutil
        def change(s):
            affected = []
            for job in s["jobs"].values():
                if job["status"] not in {"pending", "running"}:
                    continue
                owner = job.get("owner")
                if not owner:
                    continue
                try:
                    alive = abs(psutil.Process(owner["pid"]).create_time() - owner["created_at"]) < 0.001
                except psutil.Error:
                    alive = False
                if not alive:
                    job.update(status="interrupted", diagnostic="Host exited; native handle cannot reconnect")
                    s["families"][job["family"]]["status"] = "paused"
                    affected.append(job["id"])
            recovered=[]
            for request in s["requests"].values():
                owner=request.get("owner")
                if request["state"]!="reserved" or not owner:continue
                try:alive=abs(psutil.Process(owner["pid"]).create_time()-owner["created_at"])<0.001
                except psutil.Error:alive=False
                if alive:continue
                family=s["families"][request["family"]]
                family["reserved_tokens"]-=request["upper_tokens"]
                family["spent_tokens"]+=request["upper_tokens"]
                family["unknown_usage_reservations"]+=1
                if family["status"]=="running":family["status"]="paused"
                request.update(state="failed_unknown_cost",actual_tokens=None,accounted_upper_bound=request["upper_tokens"],completed_at=time.time(),recovery_reason="Physical provider owner exited; no replay or refund")
                recovered.append(request["id"])
            return {"interrupted": affected, "recovered_unknown_requests":recovered,"automatic_respawn": False, "budget_reset": False}
        return self.mutate(change)

    def resume_by_operator(self, family_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("An operator recovery reason is required")
        def change(s):
            family = s["families"][family_id]
            if family["deadline"] is not None and time.time() >= family["deadline"]:
                raise ValueError("Expired deadline is not extended by resume")
            if family["limits"]["tokens"] is not None and family["spent_tokens"] + family["reserved_tokens"] >= family["limits"]["tokens"]:
                raise ValueError("Resume cannot replenish an exhausted budget")
            family.update(status="running", resume_reason=reason)
            return {"family": family_id, "status": "running", "budget_reset": False,
                    "previous_children_respawned": False}
        return self.mutate(change)

    def interrupted_on_restart(self):
        def change(s):
            affected = []
            for j in s["jobs"].values():
                if j["status"] in {"pending", "running"}:
                    j["status"] = "interrupted"
                    j["diagnostic"] = "Native child cannot reconnect after process exit"
                    affected.append(j["id"])
            return {"interrupted": affected, "automatic_respawn": False}
        return self.mutate(change)
