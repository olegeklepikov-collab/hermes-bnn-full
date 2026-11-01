"""Native lifecycle, final-request verification, and source-engine composition."""
from pathlib import Path
import copy
import hashlib
import json
import re
import uuid
import contextvars
from .bridge import Bridge
from .codec import canonical, digest, read_json, strings
from .roles import NativeRoles
_physical_attempt=contextvars.ContextVar('bn_gsd_physical_attempt',default=None)


class Runtime:
    def __init__(self, ctx, settings_path):
        self.ctx = ctx
        self.bridge = Bridge(settings_path)
        self.settings = self.bridge.settings
        self.roles = NativeRoles(self)
        from .tool_policy import ToolPolicy
        self.tool_policy = ToolPolicy(self.settings) if self.settings.get("tool_policy") else None
        self.recovery = self.bridge.call("recover_dead", {})

    def bound_state(self,session_id,platform):
        try:
            return self.bridge.call("lookup",{"sid":session_id})
        except ValueError as exc:
            if str(exc)!="Native lifecycle did not bind this session" or not session_id or not platform or platform=="subagent":
                raise
            # Hermes deliberately does not replay on_session_start for restored conversations.
            # Identity comes from the native turn context, never from model tool arguments.
            self.bridge.call("session",{"sid":session_id,"platform":platform})
            return self.bridge.call("lookup",{"sid":session_id})

    def session_start(self, session_id, platform="", **kw):
        return self.bridge.call("session", {"sid": session_id, "platform": platform})

    def child_start(self, parent_session_id, child_session_id, child_goal="", **kw):
        managed = re.match(r"UDR_NATIVE_TASK:(UT\.[a-f0-9]{32})\n",child_goal)
        if managed:
            return self.bridge.call("session",{"sid":child_session_id,"platform":"subagent","parent":parent_session_id,"managed_task":managed.group(1)})
        match = re.match(r"GSD_NATIVE_JOB:(J\.[0-9a-f]{32})\n", child_goal)
        if match:
            return self.bridge.call("session", {"sid": child_session_id, "platform": "subagent",
                "parent": parent_session_id, "job_id": match.group(1)})
        # Generic native children inherit resource/effect restrictions but do not become G/S/D.
        return self.bridge.call("session", {"sid": child_session_id, "platform": "subagent",
                                            "parent": parent_session_id})

    def pre_model(self, **kw):
        self.bound_state(kw.get("session_id") or "",kw.get("platform") or "")
        if kw.get("platform") == "subagent":
            return {"context": "This is an already activated native leaf role. Do not orchestrate, "
                    "delegate, start a new GSD run, or request procedures. The host supplies your full "
                    "canonical context and exact input. Return the required JSON product directly."}
        return {"context": "GSD Engine 3.0.3 is connected through the native harness. For substantive GSD "
            "analysis first load skill_view bn-gsd:gsd-native-orchestration, then use gsd_research; "
            "gsd_analyze is the advanced canonical interface. "
            "for an exact operation use gsd_work and the full indexed contract. "
            "G/S/D are real bounded native leaf sessions. Source-engine computations, model review, semantic "
            "acceptance, and external permission are distinct. Never claim success for a missing executor. "
            "Use gsd_runtime_status for actual host resources; gsd_status describes the unchanged supplier bundle. Use Beads through its configured MCP because the guarded terminal cannot access private stores. Local code has no network or credential access. gsd_stop stops this family."}

    def request_middleware(self, request, session_id="", **kw):
        state = self.bound_state(session_id,kw.get("platform") or "")
        job = state.get("job")
        result = copy.deepcopy(request)
        key = "max_output_tokens" if "input" in result or (kw.get("aux_task") and kw.get("provider") == "openai-codex") else "max_completion_tokens" if "max_completion_tokens" in result else "max_tokens"
        output_limit = min(self.settings["limits"]["output_tokens"], state["family"]["limits"]["output_tokens"])
        result[key] = min(result.get(key) or output_limit, output_limit)
        if not job:
            return {"request": result, "source": "bn-gsd", "reason": "bounded provider output"}
        full = self.bridge.call("job_context", {"job_id": job["id"]})
        addition = self.delivery_text(full)
        if addition not in "\n".join(strings(result)):
            rows = result.get("messages") if isinstance(result.get("messages"), list) else result.get("input")
            if not isinstance(rows, list):
                raise ValueError("No supported native message envelope")
            row = next((v for v in reversed(rows) if isinstance(v, dict) and v.get("role") == "user"), None)
            if row is None:
                raise ValueError("No user turn for canonical context delivery")
            content = row.get("content")
            if isinstance(content, str):
                row["content"] = content + addition
            elif isinstance(content, list):
                text_type = "input_text" if "input" in result else "text"
                row["content"].append({"type": text_type, "text": addition})
            else:
                raise ValueError("Unsupported native user content")
        return {"request": result, "source": "bn-gsd", "reason": "complete addressed role context"}

    @staticmethod
    def delivery_text(full):
        return ("\n<GSD_ACTIVE_CANONICAL_CONTEXT digest=\"" + full["context"]["text_sha256"] + "\">\n" +
                full["context"]["text"] + "\n</GSD_ACTIVE_CANONICAL_CONTEXT>\n" +
                "<GSD_UNTRUSTED_INPUT sha256=\"" + full["job"]["input_digest"] + "\">\n" +
                canonical(full["inputs"]).decode() + "\n</GSD_UNTRUSTED_INPUT>\n")

    @staticmethod
    def physical_request_id(api_request_id, request, retry_count=0):
        if type(retry_count) is not int or retry_count<0:raise ValueError('Invalid native provider attempt number')
        # Native transport retries are different physical calls; a duplicate of
        # the same attempt remains forbidden. Redirect payloads remain distinct.
        return api_request_id + '.attempt-' + str(retry_count) + ".payload-" + digest({k:v for k,v in request.items() if k not in {"timeout","http_client"}})

    def model_control(self, execution_kind, payload, session_id="", api_request_id="", provider="", **kw):
        from hermes_cli.execution_control import ExecutionDecision
        state = self.bound_state(session_id,kw.get("platform") or "")
        request = payload["request"]
        if any(not isinstance(tool, dict) or tool.get("type") != "function" for tool in (request.get("tools") or [])):
            return ExecutionDecision(False, "Provider-executed tools require a separate trusted adapter")
        if provider != self.settings["provider"]:
            return ExecutionDecision(False, "Model provider is outside the approved resource scope")
        job = state.get("job")
        delivery = None
        if job:
            full = self.bridge.call("job_context", {"job_id": job["id"]})
            if self.delivery_text(full) not in "\n".join(strings(request)):
                return ExecutionDecision(False, "Mandatory role context was not delivered intact")
            delivery = {"assembled_text_sha256": full["context"]["text_sha256"],
                        "manifest_digest": full["context"]["manifest_digest"],
                        "source_bytes": full["context"]["bytes"],
                        "input_digest": full["job"]["input_digest"],
                        "final_provider_arguments_verified": True,
                        "semantic_adherence_inferred": False}
        maximum = request.get("max_output_tokens") or request.get("max_completion_tokens") or request.get("max_tokens")
        if type(maximum) is not int or not 0 < maximum <= min(self.settings["limits"]["output_tokens"], state["family"]["limits"]["output_tokens"]):
            return ExecutionDecision(False, "A bounded provider output is required")
        raw = canonical({k: v for k, v in request.items() if k not in {"timeout", "http_client"}})
        if len(raw) > min(self.settings["limits"]["request_bytes"], state["family"]["limits"].get("request_bytes", self.settings["limits"]["request_bytes"])):
            return ExecutionDecision(False, "Required context/input exceeds the request bound; split work, do not trim")
        physical_id = api_request_id + ".aux-attempt-" + str(kw.get("retry_count", 0)) if execution_kind == "auxiliary" else self.physical_request_id(api_request_id, request,kw.get('retry_count',0))
        try:
            reservation = self.bridge.call("reserve", {"sid": session_id, "request_id": physical_id,
                "fingerprint": digest(read_json(raw)), "logical_id": api_request_id, "upper_tokens": self.input_upper_bound(request,len(raw),maximum),
                "delivery": delivery,"expires_at":kw.get('execution_control_deadline'),
                "owner":{"pid":__import__("os").getpid(),"created_at":__import__("psutil").Process().create_time()}})
        except ValueError as exc:
            return ExecutionDecision(False, "GSD accounting rejected the attempt: " + str(exc))
        attempt=_physical_attempt.get()
        if attempt is not None and execution_kind!='auxiliary':attempt['id']=reservation['id']
        def abort_before_executor(reason):
            return self.bridge.call('settle',{'request_id':reservation['id'],'actual_tokens':0,'error':True})
        return ExecutionDecision(True, reservation_id=reservation["id"],on_abort=abort_before_executor)

    @staticmethod
    def input_upper_bound(request,raw_bytes,maximum):
        # Text BPE is bounded by encoded bytes. Multimodal input is bounded by the
        # verified current model's full context instead, never by the URL length.
        def media(value):
            if isinstance(value,dict):
                if value.get("type") in {"image_url","input_image","input_audio","input_file"}:return True
                return any(media(v) for v in value.values())
            if isinstance(value,list):return any(media(v) for v in value)
            return False
        baseline=raw_bytes+8192+maximum
        if media(request.get("messages",request.get("input",[]))):
            if request.get("model")!="gpt-6.1-sol":raise ValueError("A verified model context bound is required for multimedia")
            return max(baseline,1050000+maximum)
        return baseline

    def tool_control(self, payload, session_id="", **kw):
        from hermes_cli.execution_control import ExecutionDecision
        name = payload["tool_name"]
        args = payload["args"]
        if name in {"gsd_runtime_status", "gsd_stop", "gsd_read_role"}:
            return ExecutionDecision(True)
        state = self.bridge.call("lookup", {"sid": session_id})
        job = state.get("job")
        if state["family"]["status"] != "running":
            return ExecutionDecision(False, "GSD family stopped or requires recovery")
        self.bridge.call("tool_call", {"sid": session_id, "name": name})
        if state["session"].get("managed_task"):
            from .worker_policy import worker_allows
            if not worker_allows(name,args):
                return ExecutionDecision(False,"Managed UDR child is read-only; delegation and effects are forbidden")
        if name == "bn_deliver_report":
            return ExecutionDecision(not job and not state["session"].get("parent"),"Exact owner-authorized report delivery requires the native root and signed adapter grant")
        if name == "bn_udr_team":
            return ExecutionDecision(not job and not state["session"].get("parent"),"Managed UDR teams require the native root")
        if name == "bn_parallel_search":
            if job or state["session"].get("parent"):
                return ExecutionDecision(False,"Parallel collectors are root-only; recursive spawning is forbidden")
            from .parallel_search import validate
            try:validate(args)
            except ValueError as exc:return ExecutionDecision(False,str(exc))
            return ExecutionDecision(True)
        if job:
            if job.get('corpus_id'):
                allowed={'mcp__context__document_read','mcp__context__document_status','mcp__context__document_describe'}
                target,parameters=name,args
                if name=='tool_call':
                    calls=args.get('calls',[])
                    if not isinstance(calls,list) or len(calls)!=1:return ExecutionDecision(False,'One addressed document call required')
                    target,parameters=calls[0].get('name'),calls[0].get('arguments',{})
                if target in allowed:
                    cid=parameters.get('corpus_id')
                    from hermes_cli.config import load_config_readonly
                    from bn_memory.broker import Broker
                    from bn_memory.documents import Documents
                    config=load_config_readonly()['plugins']['entries']['bn-common-memory']['settings']['config_file']
                    docs=Documents(Broker(__import__('json').loads(__import__('pathlib').Path(config).read_text())))
                    if target.endswith('document_describe'):
                        if not docs.membership(session_id,job['corpus_id'],parameters['doc_id']):return ExecutionDecision(False,'Only addressed document metadata is allowed')
                    elif cid!=job['corpus_id']:return ExecutionDecision(False,'Only the addressed document corpus is allowed')
                    elif target.endswith('document_read') and not docs.membership(session_id,cid,parameters['doc_id'],parameters['unit']):return ExecutionDecision(False,'Only addressed units are allowed')
                    try:admitted=self.tool_policy.classify(target,parameters)
                    except ValueError as exc:return ExecutionDecision(False,str(exc))
                    return ExecutionDecision(bool(admitted),'Document transport must have owner admission')
            safe = name in {"gsd_role_info", "tool_search", "tool_describe"}
            return ExecutionDecision(safe, "Native G/S/D leaves may only inspect addressed sources; effects and recursive delegation are forbidden")
        if name.startswith("gsd_") or name in {"tool_search", "tool_describe", "tool_call", "skills_list", "skill_view"}:
            return ExecutionDecision(True)
        if name == "read_file":
            from hermes_cli.config_effective import load_user_config_effective
            if (load_user_config_effective().get("terminal") or {}).get("backend", "local") not in {"local", "bn_guarded_local"}:
                return ExecutionDecision(False, "Remote file backends need a separate read-scope adapter")
            from .paths import scoped_public_file,public_read_roots
            scoped_public_file(args.get("path") or "",public_read_roots(self.settings))
            return ExecutionDecision(True)
        if name in {"terminal", "read_file", "write_file", "patch", "search_files"}:
            from hermes_cli.config_effective import load_user_config_effective
            guarded = (load_user_config_effective().get("terminal") or {}).get("backend") == "bn_guarded_local"
            return ExecutionDecision(guarded, "A mandatory OS sandbox is required for local execution")
        if name == "skill_manage":
            return ExecutionDecision(args.get("action") in {"create","list_files","read_file"}, "Local skill creation/reading is allowed; altering or deleting protected skills needs a separate owner path")
        if name in {"todo", "memory", "web_search", "web_extract", "nimble_agent_bootstrap", "nimble_agent_run_result", "nimble_agent_run_start", "nimble_agent_run_status", "nimble_agents_list"}:
            return ExecutionDecision(True)
        try:
            row = self.tool_policy.classify(name, args) if self.tool_policy else None
        except ValueError as exc:
            return ExecutionDecision(False, "GSD tool admission rejected: " + str(exc))
        if row:
            if row["mode"] == "exact_owner_grant":
                self.bridge.call("authorize_tool_grant", {"sid": session_id, "name": name, "args_digest": digest(args),
                    "call_id": kw.get("tool_call_id") or "", "boundary": kw.get("boundary") or ""})
            return ExecutionDecision(True)
        return ExecutionDecision(False, "Unlisted executor: explicit trusted adapter or exact owner grant required")

    def result_control(self, payload, session_id="", tool_call_id="", **kw):
        from hermes_cli.execution_control import ExecutionDecision
        self.post_tool(tool_name=payload["tool_name"],args=payload["args"],result=payload["result"],session_id=session_id,tool_call_id=tool_call_id)
        return ExecutionDecision(True)

    def post_tool(self, tool_name="", args=None, result=None, session_id="", tool_call_id="", **kw):
        if not session_id or tool_name.startswith("gsd_"):
            return
        return self.bridge.call("evidence_event", {"sid": session_id, "event": {
            "tool_name": tool_name, "tool_call_id": tool_call_id, "arguments_sha256": digest(args or {}),
            "result_sha256": digest(result), "source": "actual_native_tool_result",
            "reading_level": "tool_return_only", "source_truth_verified": False}})

    def model_execution(self, request, next_call, api_request_id="", **kw):
        # The native interrupt path exits before post_api_request/api_request_error.
        # This supported execution middleware closes its exact reservation before
        # propagating a failure. Unknown usage is charged at the preserved bound;
        # no provider replay, refund, or authorization bypass is performed.
        fallback_id = self.physical_request_id(api_request_id, request,kw.get('retry_count',0))
        attempt={};token=_physical_attempt.set(attempt)
        try:
            response = next_call(request)
        except BaseException:
            self.bridge.call("settle", {"request_id": attempt.get('id',fallback_id), "error": True})
            raise
        finally:
            _physical_attempt.reset(token)
        # A received response may subsequently be discarded by a native redirect.
        # Account it here as well; the later observer remains idempotent.
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        total = usage.get("total_tokens") if isinstance(usage, dict) else getattr(usage, "total_tokens", None)
        self.bridge.call("settle", {"request_id": attempt.get('id',fallback_id),
            "actual_tokens": total if type(total) is int and total >= 0 else None})
        return response

    def post_api(self, api_request_id="", usage=None, error=None, **kw):
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        physical_id = api_request_id + (".aux-attempt-" + str(kw.get("retry_count", 0)) if kw.get("aux_task") else "")
        return self.bridge.call("settle", {"request_id": physical_id, "actual_tokens": total,
                                            "error": error is not None})

    def session_end(self, session_id, interrupted=False, **kw):
        state = self.bridge.call("lookup", {"sid": session_id})
        if interrupted and not state.get("job") and not state.get("session", {}).get("parent"):
            self.bridge.call("stop", {"sid": session_id, "reason": "Native parent interrupted"})
            self.roles.stop(session_id)

    def analyze(self, args, sid):
        self.bridge.call("validate_analysis", {"components": args["components"], "request": args["request"]})
        self.bridge.call("phase", {"sid": sid, "phase": "working"})
        active = args["components"]
        request = args["request"]
        native = {}
        provider = None
        if "G" in active and request.get("generation", {}).get("method") == "agent":
            generation = request["generation"]
            self.bridge.call("validate_generation", {"generation": generation})
            generation_inputs = {"generation": generation,
                "construction_observations": [o for o in request.get("observations", [])
                                              if o.get("used_for_generation") is True],
                "seed_origin": "unattested_input_unless_explicitly_bound"}
            if args.get('corpus_id'):generation_inputs['document_corpus']=args['corpus_id']
            if args.get("resume_G_job"):
                native["G"] = self.bridge.call("resume_generation", {"sid": sid,
                    "job_id": args["resume_G_job"], "inputs": generation_inputs})
            else:
                native["G"] = self.roles.run(sid, "G", "generation", generation_inputs, args["request_id"] + ".G",corpus_id=args.get('corpus_id'))
            self.bridge.call("validate_candidates", {"candidates": native["G"]["result"]["candidates"],
                                                       "generation": generation})
            provider = self.bridge.call("provider_receipt", {"job_id": native["G"]["id"],
                                                              "generation": generation})["provider_config"]
        finite = self.bridge.engine("gsd_execute", {k: v for k, v in args.items() if k not in {"resume_G_job", "corpus_id"}}, provider, sid=sid)
        if finite.get("ok") is not True:
            return finite
        outcome = finite["result"]
        engine = outcome.get("engine_result", {})
        for role in "SD":
            if role not in active or role not in engine.get("executed_components", []):
                continue
            predecessors = [native["S"]] if role == "D" and "S" in native else list(native.values())
            handoffs = [self.bridge.call("native_handoff", {"job_id": v["id"], "receiver": role,
                        "profile": engine["profile"]["selected"], "scope": request["scope"]})
                        for v in predecessors]
            inputs = {"scope": request["scope"], "question": request["question"],
                      "profile": engine["profile"], "finite_role_result": engine["outputs"][role],
                      "candidate_field": engine.get("candidate_field", []),
                      "comparison_review": engine.get("outputs", {}).get("S") or request.get("review"),
                      "finite_review_programmatically_validated_by_source_D": "D" in engine.get("executed_components", []),
                      "finite_review_method": "Exact canonical JSON comparison only for observation keys present in candidate expectations; unmatched keys are not classified by that finite algorithm; subject-matter truth remains unreviewed",
                      "native_predecessor_products": {v["role"]: {"job_id": v["id"], "result": v["result"],
                          "native_result_hash": v["native_receipt"]["result_hash"]} for v in predecessors},
                      "observations": request.get("observations", []) if role == "S" or not handoffs else [],
                      "native_predecessor_handoffs": handoffs,
                      "supplied_review_origin": "unattested_input" if "S" not in active else "original_finite_S_algorithm",
                      "profile_obligations": engine.get("unmet_profile_obligations", [])}
            if not handoffs:
                inputs["supplied_candidate_field"] = engine.get("candidate_field", [])
                inputs["supplied_review"] = request.get("review")
            try:
                native[role] = self.roles.run(sid, role, "semantic_analysis", inputs, args["request_id"] + "." + role,corpus_id=args.get('corpus_id'))
            except Exception as exc:
                outcome["native_failed_role"] = role
                outcome["native_error"] = str(exc)
                break
        outcome["native_role_jobs"] = {role: {"id": job["id"], "result": job["result"],
            "native_receipt": job["native_receipt"]} for role, job in native.items()}
        outcome["semantic_acceptance"] = "actual_native_model_products_require_the_declared_subject_matter_review"
        outcome["generation_observation_delivery"] = "Only declared construction observations were given to native G; holdout observations were withheld"
        outcome["external_action_authorized"] = False
        self.bridge.call("phase", {"sid": sid, "phase": "finalizing"})
        if outcome.get("native_failed_role"):
            finite["ok"] = False
            outcome["effective_status"] = "partial_native_execution"
        return finite

    def read_role(self, args, sid):
        # Retrieval is not a new analysis. Never replay a model or expose job control.
        state=self.bridge.call("lookup",{"sid":sid})
        if state.get("job") or state["session"].get("parent"):
            raise PermissionError("completed_role_reader_requires_native_root")
        job=self.bridge.call("job_get",{"job_id":args["job_id"]})
        if job["family"]!=state["session"]["family"]:
            raise PermissionError("completed_role_outside_family")
        receipt=job.get("native_receipt") or {}
        if job["status"]!="completed" or receipt.get("terminal_state")!="SUCCEEDED":
            raise PermissionError("successful_completed_role_required")
        offset=args.get("offset",0);limit=args.get("max_chars",4096)
        if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=4096:
            raise ValueError("completed_role_page_bounds_invalid")
        from agent.subagent_products import read_text_product
        from types import SimpleNamespace
        original=read_text_product(SimpleNamespace(structured_payload=receipt.get("product_ref")))
        view=args.get("view","validated")
        if view=="original":text=original
        elif view=="validated":text=json.dumps(job["result"],ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
        else:raise ValueError("unknown_completed_role_view")
        if offset>len(text):raise ValueError("completed_role_offset_outside_text")
        end=min(offset+limit,len(text));fragment=text[offset:end]
        return {"job_id":job["id"],"role":job["role"],"child_session_id":job["child_session_id"],
            "view":view,"status":job["status"],"terminal_state":receipt["terminal_state"],
            "original_product_sha256":receipt["product_ref"]["sha256"],"text":fragment,
            "text_sha256":hashlib.sha256(text.encode()).hexdigest(),"fragment_sha256":hashlib.sha256(fragment.encode()).hexdigest(),"offset":offset,"end_offset":end,
            "next_offset":end if end<len(text) else None,"complete":end==len(text),"total_characters":len(text),
            "offset_unit":"Unicode code points","executor_repeated":False,"truth_accepted":False,
            "private_job_controls_exposed":False}

    def research(self, args, sid):
        # Bind structure only. Hypotheses and reviews are produced by the same
        # genuine native G/S/D implementation, never by this adapter.
        request = {"scope": args["scope"], "question": args["question"], "candidates": [],
            "requested_profile": args.get("requested_profile", "Standard"),
            "observations": [{**o, "used_for_generation": True} for o in args.get("observations", [])],
            "generation": {"id": args["request_id"] + ".G", "task": args["question"],
                "seed": args["question"], "scope": args["scope"], "product_kind": "hypothesis",
                "frame": args.get("frame", "Distinct process, measurement, null and risky-omission alternatives"),
                "constraints": args.get("constraints", []), "method": "agent",
                "max_candidates": args.get("max_candidates", 4), "scan_budget": 20}}
        if "risk" in args:
            request["risk"] = args["risk"]
        return self.analyze({"components": "GSD", "request_id": args["request_id"], "request": request,
            **({'corpus_id':args['corpus_id']} if args.get('corpus_id') else {}),
            **({"resume_G_job": args["resume_G_job"]} if args.get("resume_G_job") else {})}, sid)

    def work(self, args, sid):
        key = args["key"]
        contract = self.bridge.engine("gsd_contract", {"key": key}, sid=sid)
        if not contract.get("ok"):
            return contract
        value = contract["result"]
        role = value.get("owning_component") or value.get("owner")
        if role not in {"G", "S", "D"}:
            return {"ok": False, "error": {"code": "REFERENCE_NOT_EXECUTOR",
                "message": "This source element is a definition, not an executable G/S/D procedure"}}
        procedure_ids = [key.split(":", 1)[1]] if key.startswith("procedure:") else []
        if procedure_ids:
            if not args.get("run_id"):
                return {"ok": False, "status": "needs_data", "error": {
                    "code": "PROCEDURE_CASE_REQUIRED", "message": "A ready source ProcedureEngine case is required"},
                    "semantic_execution_performed": False}
            prepared = self.bridge.call("procedure_inputs", {"sid": sid, "run_id": args["run_id"],
                "procedure_id": procedure_ids[0], "declared_inputs": args["inputs"]})
            if not prepared["ready"]:
                return {"ok": False, "status": "awaiting_dependency", "next": prepared["next"],
                        "semantic_execution_performed": False}
            args = {**args, "inputs": prepared}
        job = self.roles.run(sid, role, key, {"contract": value, "inputs": args["inputs"]},
                             args["request_id"], procedure_ids=procedure_ids,
                             entry_keys=[] if procedure_ids else value.get("source_anchors", []), profile=args.get("context_profile", "standard"),corpus_id=args.get("corpus_id"))
        return {"ok": True, "result": job, "procedure_committed": False,
                "next_required": "Validate addressable outputs and the actual postcondition before source ProcedureEngine commit"}

    def work_file(self, args, sid):
        if args["interpretation"] != "independent_records":
            raise ValueError("Only explicitly independent records can be partitioned by this adapter")
        plan = self.bridge.call("prepare_work_file", {k: v for k, v in args.items() if k != "interpretation"})
        results = []
        for operation in plan.pop("operations"):
            try:
                result = self.work(operation, sid)
            except Exception as exc:
                result = {"ok": False, "error": {"message": str(exc)}}
            results.append(result)
            if not result.get("ok"):
                break
        return {"ok": len(results) == plan["source_records"] and all(r.get("ok") for r in results),
                "plan": plan, "products": results, "completed_record_indices": list(range(sum(r.get("ok") is True for r in results))),
                "scope": "Independent per-record products only; joint inference requires a separate evidence-preserving task"}
