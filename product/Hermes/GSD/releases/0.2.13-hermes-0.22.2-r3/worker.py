#!/usr/bin/env python3
"""Single locked boundary to the unchanged GSD service and its signed Store."""
from pathlib import Path
import argparse
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bn_gsd.codec import canonical, digest, read_json
from bn_gsd.ledger import HostLedger


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def blob(settings, value):
    raw = canonical(value)
    sha = hashlib.sha256(raw).hexdigest()
    path = Path(settings["state_dir"]) / "blobs" / (sha + ".json")
    if not path.exists():
        atomic(path, raw)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("Changed immutable context/input blob")
    return sha


def load_blob(settings, sha):
    if len(sha) != 64 or any(x not in "0123456789abcdef" for x in sha):
        raise ValueError("Invalid blob identity")
    raw = (Path(settings["state_dir"]) / "blobs" / (sha + ".json")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("Blob integrity failure")
    return read_json(raw)


from bn_gsd.anchor_store import check_anchor, anchor, install_store_guard


def execute(settings, operation, args):
    root = Path(settings["bundle_root"]).resolve()
    if hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() != settings["integration_manifest_sha256"]:
        raise ValueError("Installed GSD integration manifest changed")
    if hashlib.sha256((root / "engine/manifest.json").read_bytes()).hexdigest() != settings["engine_manifest_sha256"]:
        raise ValueError("Installed GSD Engine manifest changed")
    for name in ["store_key", "native_key", "grant_key"]:
        p = Path(settings[name])
        if p.is_symlink() or p.stat().st_mode & 0o077 or len(p.read_bytes()) != 32:
            raise ValueError("Invalid operator key or permissions")
    os.environ["GSD_STATE_DIR"] = settings["state_dir"]
    os.environ["GSD_TRUST_KEY_FILE"] = settings["store_key"]
    os.environ.pop("GSD_PROVIDER_CONFIG", None)
    os.environ.pop("GSD_HOST_POLICY", None)
    sys.path.insert(0, str(root))
    from gsd_bridge.common import verify_tree
    check = verify_tree(root)
    if not check["valid"]:
        raise ValueError("Supplied GSD code or corpus failed integrity validation")
    from gsd_bridge.service import Service
    install_store_guard(settings)
    service = Service()
    ledger = HostLedger(service.store, settings["limits"])
    functions = {
        "session": lambda: ledger.session(**args),
        "lookup": lambda: ledger.lookup(**args),
        "reserve": lambda: ledger.reserve(**args),
        "settle": lambda: ledger.settle(**args),
        "stop": lambda: ledger.stop(**args),
        "finish_job": lambda: ledger.finish_job(**args),
        "restart": ledger.interrupted_on_restart,
        "job_get": lambda: ledger.get_job(**args),
        "family_status": lambda: ledger.family_status(**args),
        "phase": lambda: ledger.phase(**args),
        "bind_case": lambda: ledger.bind_case(**args),
        "recover_dead": ledger.recover_dead_owners,
        "operator_resume": lambda: ledger.resume_by_operator(**args),
        "operator_output_limit": lambda: ledger.operator_output_limit(**args),
        "operator_request_limit": lambda: ledger.operator_request_limit(**args),
        "operator_observation_mode": lambda: ledger.operator_observation_mode(**args),
        "tool_call": lambda: ledger.tool_call(**args),
        "revoke_grant": lambda: ledger.revoke_grant(**args),
    }
    if operation == "evidence_event":
        def record(state):
            family=state["sessions"][args["sid"]]["family"]
            event={**args["event"],"family":family,"time":time.time()}
            state["events"].append(event)
            for grant in state.get("grants",{}).values():
                if grant.get("state")=="tool_inflight" and grant.get("call_id")==args["event"].get("tool_call_id"):
                    grant["state"]="completed"
            return {"recorded":True,"event_sha256":digest(event)}
        return ledger.mutate(record)
    if operation in {"issue_tool_grant","authorize_tool_grant"}:
        from bn_gsd import tool_grants
        return (tool_grants.issue if operation=="issue_tool_grant" else tool_grants.authorize)(settings,ledger,**args)
    if operation == "operator_migrate":
        # Original signed 1.0 -> 1.1 migration; foreign/ambiguous state is rejected by the supplier.
        if args.get("apply"):
            plan=service.migrate_by_host(backup_path=args["backup_path"],apply=False)
            known=ledger.read(lambda state:set(state.get("case_families",{})))
            if plan["runs"]:
                raise ValueError("Old runs lack attested Hermes resource accounting; inspect/reconcile instead of inventing or resetting spend")
        return service.migrate_by_host(**args)
    if operation == "init":
        return ledger.mutate(lambda s: {"initialized": True, "schema": s["schema"]})
    if operation in functions:
        return functions[operation]()
    if operation == "validate_generation":
        result = service.modules["triad"].GenerationComponent().run(args["generation"], provider=None)
        return {"valid_input_contract": True, "supplier_state": result.get("status"),
                "semantic_generation_performed": False}
    if operation == "validate_analysis":
        request = args["request"]
        triad = service.modules["triad"]
        triad.choose_profile(request.get("requested_profile", "eMVP"), request.get("risk", {k: None for k in triad.RISK_KEYS}))
        triad.validate_comparison_inputs(request.get("candidates", []), request.get("observations", []), request["scope"])
        if "D" in args["components"]:
            triad.require_text(request["question"], "question")
        if "G" in args["components"]:
            generation = request["generation"]
            if generation["scope"] != request["scope"]:
                raise ValueError("SCOPE_MISMATCH before native launch: generation.scope must equal request.scope exactly")
            if generation.get("method") == "agent":
                triad.GenerationComponent().run(generation, provider=None)
        return {"input_contract_checked": True, "model_execution_performed": False}
    if operation == "component_inventory":
        triad = service.modules["triad"]
        return {"engine_release": service.status()["engine"]["release"], "integration_release": "1.1.0",
                "component_versions": {"G": triad.GenerationComponent.version,
                    "S": triad.StrictComponent.version, "D": triad.DiagnosticComponent.version},
                "comparison_contract": triad.COMPARISON_CONTRACT, "source_tree_verified": check["valid"],
                "separate_original_lab_adapter_1_2_available": False}
    if operation == "validate_candidates":
        candidates = args["candidates"]
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Missing native candidate field")
        for candidate in candidates:
            service.modules["triad"].validate_candidate(candidate)
            if candidate["scope"] != args["generation"]["scope"]:
                raise ValueError("Candidate scope changed")
        if len({c["id"] for c in candidates}) != len(candidates):
            raise ValueError("Repeated native candidate IDs")
        return {"valid_candidate_contracts": True, "semantic_truth_established": False}
    if operation in {"issue_grant", "artifact"}:
        from bn_gsd import effects
        if operation == "issue_grant":
            return effects.issue(settings, ledger, **args)
        return effects.execute(settings, ledger, checkpoint=anchor, **args)
    if operation == "operator_attach":
        current = service.call("gsd_case_get", {"run_id": args["run_id"]})
        if not current["ok"]:
            return current
        return ledger.bind_case(args["sid"], current["result"]["case"]["case_id"], allow_join=True)
    if operation in {"engine", "model_engine"}:
        config = args.get("provider_config")
        if config:
            p = Path(config).resolve()
            if not p.is_relative_to(Path(settings["operator_dir"]).resolve()):
                raise ValueError("Provider configuration is not operator-owned")
            os.environ["GSD_PROVIDER_CONFIG"] = str(p)
        tool, arguments = args["tool"], dict(args["arguments"])
        if operation == "model_engine":
            sid = args["sid"]
            native = ledger.lookup(sid)
            HostLedger._running(native["family"])
            if native.get("job"):
                raise ValueError("Native leaf cannot orchestrate source operations")
            family = native["session"]["family"]
            if "run_id" in arguments:
                current = service.call("gsd_case_get", {"run_id": arguments["run_id"]})
                if not current.get("ok"):
                    return current
                ledger.own_case(sid, current["result"]["case"]["case_id"])
            if tool == "gsd_case_create":
                # Bind before allocation; an existing case cannot be adopted by guessing its ID.
                ledger.bind_case(sid, arguments["case"]["case_id"])
            if tool == "gsd_case_change" and arguments["operation"] in {"commit", "accept_limited", "close"}:
                return {"ok": False, "error": {"code": "HOST_POSTCONDITION_REVIEW_REQUIRED",
                    "message": "A model claim cannot admit its own procedure postcondition; use the operator review command"},
                    "external_effect_performed": False}
            if tool == "gsd_product_register":
                arguments["namespace"] = family + "." + arguments["namespace"]
            if tool in {"gsd_product_get", "gsd_product_handoff"}:
                product = service.products.get(arguments["product_id"], current_required=False)
                ledger.own_product(sid, product["namespace"])
            if tool in {"gsd_execute", "gsd_case_create"}:
                arguments["request_id"] = family + "." + arguments["request_id"]
        result = service.call(tool, arguments)
        if operation == "model_engine" and tool == "gsd_case_change" and arguments["operation"] == "stop" and result.get("ok") and result["result"].get("operation_accepted"):
            ledger.stop(sid, arguments["payload"]["reason"])
        return result
    if operation == "operator_case_change":
        if args["operation"] not in {"accept_limited", "close", "stop", "insert_repair", "refresh"}:
            raise ValueError("Use native-job postcondition admission for commit")
        current = service.case_get(args["run_id"])
        ledger.own_case(args["sid"], current["case"]["case_id"])
        result = service.call("gsd_case_change", {k: v for k, v in args.items() if k != "sid"})
        if args["operation"] == "stop" and result.get("ok") and result["result"].get("operation_accepted"):
            ledger.stop(args["sid"], args["payload"]["reason"])
        return result
    if operation == "operator_case_resume":
        current = service.case_get(args["run_id"])
        ledger.own_case(args["sid"], current["case"]["case_id"])
        resumed = service.resume_by_host(args["run_id"], args["expected_store_revision"], args["reason"])
        try:
            host = ledger.resume_by_operator(ledger.lookup(args["sid"])["session"]["family"], args["reason"])
        except Exception:
            service.case_change(args["run_id"], "HOST-RESUME-REFUSED." + str(time.time_ns()), resumed["store_revision"],
                "stop", {"reason": "Host resource/deadline did not permit resume"})
            raise
        return {"source": resumed, "host": host}
    if operation == "operator_new_run":
        current = service.case_get(args["arguments"]["previous_run_id"])
        ledger.own_case(args["sid"], current["case"]["case_id"])
        HostLedger._running(ledger.lookup(args["sid"])["family"])
        result = service.new_run_by_host(**args["arguments"])
        return {"source": result, "host_budget_reset": False,
                "host_family": ledger.lookup(args["sid"])["session"]["family"]}
    if operation == "operator_external_commit":
        job=ledger.get_job(args["job_id"])
        if job["status"]!="completed" or not job["operation"].startswith("procedure:"):
            raise ValueError("A real completed external native procedure job is required")
        HostLedger._running(ledger.lookup(job["parent_session_id"])["family"])
        inputs=load_blob(settings,job["inputs_ref"])["inputs"]
        ready=inputs["source_ready_step"]
        if not ready.get("external_executor") or inputs["source_case"]["run_id"]!=args["run_id"]:
            raise ValueError("Job is not the outstanding external procedure")
        current=service.case_next(args["run_id"])
        external=current["next"].get("external_request")
        if not external or external["input_fingerprint"]!=ready["input_fingerprint"]:
            raise ValueError("External inputs changed")
        if not args.get("review_reason","").strip():raise ValueError("Explicit postcondition review required")
        context=load_blob(settings,job["context_ref"])
        if context["manifest_digest"]!=external["context_manifest_digest"] or context["text_sha256"]!=external["context_text_sha256"]:
            raise ValueError("External canonical context differs")
        artifacts={v["id"]:v for v in service.case_get(args["run_id"])["case"]["artifacts"]}
        payload=args["payload"]
        body={"id":args["request_id"],"producer":"Hermes-native-external","run_id":args["run_id"],
            "procedure_id":external["procedure"]["id"],"case_revision":external["case_revision"],
            "input_fingerprint":external["input_fingerprint"],"context_manifest_digest":external["context_manifest_digest"],
            "context_text_sha256":external["context_text_sha256"],"context_delivery_attested":True,
            "output_digests":{identifier:digest(artifacts[identifier]) for identifier in payload["output_ids"]},
            "status":payload["status"],"postcondition_observed":payload["postcondition_observed"],
            "reason":args["review_reason"]+" [native job "+job["id"]+"]","cost":payload["cost"],
            "deadline":datetime.fromtimestamp(time.time()+120,timezone.utc).isoformat()}
        from gsd_bridge.routes import signature,accept_external
        key=Path(settings["native_key"])
        policy=Path(settings["operator_dir"])/"external-host-policy.json"
        configured=read_json(policy.read_bytes())["procedure_executors"].get("Hermes-native-external")
        if not configured or configured.get("enabled") is not True or job["role"] not in configured.get("components",[]) or Path(configured["key_file"]).resolve()!=key.resolve():
            raise ValueError("External executor missing, revoked or outside its component scope")
        os.environ["GSD_HOST_POLICY"]=str(policy)
        receipt={**body,"signature":signature(body,key.read_bytes())}
        result=accept_external(service,receipt)
        return {"source":result,"receipt_sha256":digest(receipt),"native_job_id":job["id"],
            "independent_professional_review":False,"host_budget_reset":False}
    if operation == "operator_commit":
        job = ledger.get_job(args["job_id"])
        if job["status"] != "completed" or not job["operation"].startswith("procedure:"):
            raise ValueError("Review requires a completed real native procedure job")
        native_inputs = load_blob(settings, job["inputs_ref"])["inputs"]
        source = native_inputs["source_case"]
        ready = native_inputs["source_ready_step"]
        if source["run_id"] != args["run_id"] or ready["procedure"]["id"] != args["payload"]["procedure_id"]:
            raise ValueError("Review is not bound to this job's source case and procedure")
        current = service.call("gsd_case_next", {"run_id": args["run_id"]})
        if not current["ok"] or current["result"]["next"].get("input_fingerprint") != ready.get("input_fingerprint"):
            raise ValueError("Procedure inputs changed; previous native result requires revision")
        if not args.get("review_reason", "").strip():
            raise ValueError("Explicit subject-matter postcondition review is required")
        payload = dict(args["payload"])
        payload["reason"] = args["review_reason"] + " [native job " + job["id"] + "]"
        return service.call("gsd_case_change", {"run_id": args["run_id"], "request_id": args["request_id"],
            "expected_store_revision": current["result"]["store_revision"], "operation": "commit", "payload": payload})
    if operation == "job_create":
        context = service.context(components=args["role"], procedure_ids=args.get("procedure_ids", []),
                                  entry_keys=args.get("entry_keys", []), profile=args.get("profile", "standard"),
                                  byte_limit=8 * 1024 * 1024)
        context_ref = blob(settings, context)
        inputs_ref = blob(settings, args["inputs"])
        return ledger.create_job(args["sid"], args["role"], args["operation"], context_ref,
                                 inputs_ref, digest(args["inputs"]), args["request_id"], owner=args.get("owner"),corpus_id=args['inputs'].get('document_corpus'))
    if operation == "prepare_work_file":
        from bn_gsd.paths import scoped_public_file
        path = scoped_public_file(args["path"], [settings["workspace"]])
        if not path.is_file():
            raise ValueError("Independent-record input must be a local workspace file")
        if path.stat().st_size > 24 * 1024 * 1024:
            raise ValueError("Input exceeds 24 MiB; decompose the source into separately hashed files")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args["sha256"]:
            raise ValueError("Input file changed; revise its binding before execution")
        records = read_json(raw)
        if not isinstance(records, list) or not 1 <= len(records) <= 32 or any(not isinstance(r, dict) for r in records):
            raise ValueError("Expected 1–32 independent complete JSON records; no implicit splitting of indivisible records")
        # Each operation repeats its ENTIRE source closure. Source records are
        # partitioned; mandatory instructions are never partitioned or trimmed.
        jobs = [{"key": args["key"], "inputs": {"record": r, "source_sha256": args["sha256"],
                 "source_record_index": n, "interpretation": "independent_record_not_global_inference"},
                 "request_id": args["request_id"] + "." + str(n),
                 "context_profile": args.get("context_profile", "standard")} for n, r in enumerate(records)]
        return {"operations": jobs, "coverage_indices": list(range(len(records))), "source_records": len(records),
                "source_sha256": args["sha256"], "source_bytes": len(raw), "truncated": False,
                "global_inference_authorized": False}
    if operation == "procedure_inputs":
        current = service.case_get(args["run_id"])
        case = current["case"]
        ledger.own_case(args["sid"], case["case_id"])
        HostLedger._running(ledger.lookup(args["sid"])["family"])
        step = service.case_next(args["run_id"])["next"]
        external=step.get("external_request")
        if external and external["procedure"]["id"]==args["procedure_id"] and not external["missing_inputs"]:
            step={**external,"procedure":external["procedure"],"external_executor":True}
        if not step.get("procedure") or step["procedure"]["id"] != args["procedure_id"] or step.get("missing_inputs"):
            return {"ready": False, "next": step}
        procedure = step["procedure"]
        records = service.modules["records"]
        nodes, groups = records.indexes(case)
        roots = [x["id"] for group in procedure["read_set"] for x in case.get(group, [])]
        dependencies = [r for r in case.get("procedure_runs", []) if r["procedure_id"] in procedure["dependencies"]]
        roots.extend(ref for row in dependencies for ref in row["output_ids"])
        pending, selected = list(roots), {}
        while pending:
            identifier = pending.pop()
            if identifier in selected:
                continue
            if identifier not in nodes:
                raise ValueError("Unresolved mandatory data dependency: " + identifier)
            node = nodes[identifier]
            selected[identifier] = {"collection": groups[identifier], "object": node, "sha256": digest(node)}
            pending.extend(records.object_refs(node, groups[identifier]))
        case_header = {k: case[k] for k in ["case_id", "version", "revision", "contract", "risk", "requested_profile", "data_kind"]}
        return {"ready": True, "declared_inputs": args["declared_inputs"],
                "source_case": {"run_id": current["run_id"], "store_revision": current["store_revision"], "case": case_header},
                "source_ready_step": step, "source_dependency_nodes": selected,
                "accepted_dependency_records": dependencies, "data_closure_truncated": False}
    if operation == "job_context":
        job = ledger.get_job(args["job_id"])
        return {"job": job, "context": load_blob(settings, job["context_ref"]),
                "inputs": load_blob(settings, job["inputs_ref"])}
    if operation == "resume_generation":
        job = ledger.get_job(args["job_id"])
        current = ledger.lookup(args["sid"])
        HostLedger._running(current["family"])
        if job["family"] != current["session"]["family"]:
            raise ValueError("Generation recovery belongs to another family")
        if job["role"] != "G" or job["operation"] != "generation" or job["status"] != "completed":
            raise ValueError("Recovery requires an actual completed G job")
        if job["native_receipt"].get("terminal_state") != "SUCCEEDED" or not job["native_receipt"].get("result_hash"):
            raise ValueError("Recovery lacks a successful native execution receipt")
        if load_blob(settings, job["inputs_ref"]) != args["inputs"]:
            raise ValueError("Recovery input differs from the preserved G input")
        return job
    if operation == "native_handoff":
        job = ledger.get_job(args["job_id"])
        if job["status"] != "completed" or args["receiver"] not in {"G", "S", "D"}:
            raise ValueError("Completed producer and a real receiving role are required")
        inputs = load_blob(settings, job["inputs_ref"])
        source_context = load_blob(settings, job["context_ref"])
        registered = service.products.register(namespace=job.get("product_namespace", "NATIVE." + job["family"]), logical_key=job["id"],
            product={"component": job["role"], "status": "unreviewed", "native_product": job["result"],
                     "native_result_hash": job["native_receipt"]["result_hash"]},
            input_objects={"native_inputs": inputs}, origin_component=job["role"], origin_ref=job["id"],
            expected_version=0, request_id="REGISTER." + job["id"])["product"]
        family = ledger.lookup(job["parent_session_id"])["family"]
        message_id = "HANDOFF." + job["id"] + "." + args["receiver"]
        previous = ledger.read(lambda state: state["deliveries"].get(message_id))
        # A transfer has a finite freshness lease even when the overall family
        # has no wall-clock cap. Preserve the original lease on a duplicate.
        deadline = (previous["packet"]["message"]["deadline"] if previous else
            datetime.fromtimestamp(min(family["deadline"] or float("inf"),
                time.time() + settings.get("handoff_lease_seconds", 900)), timezone.utc).isoformat())
        header = {"id": message_id, "receiver": args["receiver"],
            "component_versions": {k: "3.0" for k in "GSD"},
            "corpus_digest": source_context["manifest"]["corpus_digest"],
            "risk_floor": args["profile"],
            "deadline": deadline,
            "budget_reservation": "RESERVE." + message_id, "budget_amount": 1,
            "residuals": job["result"].get("residuals") or service.modules["triad"].residuals()}
        call = {"product_id": registered["id"], "product_version": registered["version"],
            "header": header, "input_objects": {"native_inputs": inputs},
            "context": {"scope": args["scope"], "intended_use": "analysis_only"},
            "standard": {"profile": args["profile"], "semantic_acceptance": "not_inferred_from_structure"}}
        # Freshness precedes durable duplicate suppression, exactly as in the original channel.
        packet = service.products.prepare_handoff(**call)
        fingerprint = digest(packet["message"])
        def delivery(s):
            previous = s["deliveries"].get(message_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("Handoff identity conflict")
                return {**previous["packet"], "durable_duplicate": True}
            f = s["families"][job["family"]]
            HostLedger._running(f)
            if f["limits"].get("budget_mode") != "observe" and f.get("handoff_units", 0) >= f["limits"].get("handoff_units", 128):
                raise ValueError("Shared handoff budget exhausted")
            channel = service.modules["triad"].HandoffChannel(
                component_versions=header["component_versions"], corpus_digest=header["corpus_digest"],
                budget=service.modules["triad"].SharedBudget(2, reserve=0), risk_floor=args["profile"])
            receipt = channel.send(packet["message"], objects=packet["objects"], receiver=args["receiver"])
            result = {**packet, "local_channel_receipt": receipt, "durable_duplicate": False,
                      "actual_model_delivery": "pending_receiver_request_verification"}
            f["handoff_units"] = f.get("handoff_units", 0) + 1
            s["deliveries"][message_id] = {"fingerprint": fingerprint, "packet": result}
            return result
        return ledger.mutate(delivery)
    if operation == "provider_receipt":
        job = ledger.get_job(args["job_id"])
        if job["role"] != "G" or job["status"] != "completed":
            raise ValueError("No real completed native G executor")
        data = load_blob(settings, job["inputs_ref"])
        context = load_blob(settings, job["context_ref"])
        if data["generation"] != args["generation"]:
            raise ValueError("Provider request differs from native G input")
        candidates = job["result"]["candidates"]
        body = {"request_digest": digest(args["generation"]), "context_digest": context["manifest_digest"],
                "candidates": candidates, "native_receipt": job["native_receipt"],
                "deadline": time.time() + 180, "job_id": job["id"]}
        key = Path(settings["native_key"]).read_bytes()
        receipt = {"body": body, "mac": hmac.new(key, canonical(body), hashlib.sha256).hexdigest()}
        path = Path(settings["operator_dir"]) / "receipts" / (job["id"] + ".json")
        atomic(path, canonical(receipt))
        config = {"argv": [settings["python"], "-I", "-B", str(Path(__file__).with_name("provider_receipt.py")),
                           "--receipt", str(path), "--key", settings["native_key"]],
                  "provider_id": "Hermes-native-G-completion", "timeout_seconds": 30,
                  "entry_keys": [], "context_byte_limit": 8 * 1024 * 1024}
        config_path = path.with_suffix(".provider.json")
        atomic(config_path, canonical(config))
        return {"provider_config": str(config_path), "native_job": job["id"]}
    raise ValueError("Unknown host operation")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--settings", required=True)
    a = p.parse_args()
    settings_path = Path(a.settings).resolve()
    settings = read_json(settings_path.read_bytes())
    body = read_json(sys.stdin.buffer.read(24 * 1024 * 1024 + 1))
    if not isinstance(body, dict) or set(body) != {"operation", "arguments"} or not isinstance(body["arguments"], dict):
        raise ValueError("Invalid worker request")
    operator = Path(settings["operator_dir"])
    operator.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = operator / "worker.lock"
    with lock.open("a+b") as f:
        os.chmod(lock, 0o600)
        fcntl.flock(f, fcntl.LOCK_EX)
        check_anchor(settings, body["operation"] == "init")
        try:
            result = execute(settings, body["operation"], body["arguments"])
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": {"code": getattr(exc, "code", type(exc).__name__),
                                                "message": str(exc)}}
        anchor(settings)
    print(canonical(response).decode())
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(canonical({"ok": False, "error": {"code": type(exc).__name__, "message": str(exc)}}).decode())
        raise SystemExit(2)
