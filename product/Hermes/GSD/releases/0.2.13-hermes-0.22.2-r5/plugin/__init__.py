"""Hermes registration is at the edge; original GSD executes in its own process."""
from pathlib import Path
import json
import sys


def register(ctx):
    if not hasattr(ctx, "register_execution_control"):
        raise RuntimeError("The required native execution-control capability is unavailable")
    package = Path(ctx.get_config("package_root")).resolve()
    sys.path.insert(0, str(package))
    compatibility = Path(ctx.get_config("core_manifest") or package / "release/core-manifest.json")
    import hermes_cli
    from runtime_guard import verify, require_profile_binding
    verify(Path(hermes_cli.__file__).resolve().parent.parent, compatibility)
    from hermes_constants import get_hermes_home
    require_profile_binding(get_hermes_home())
    from bn_gsd.runtime import Runtime
    from bn_gsd.codec import canonical
    runtime = Runtime(ctx, ctx.get_config("settings_file"))
    from bn_gsd.sandbox import provider
    ctx.register_terminal_environment_provider(provider(runtime.settings))
    ctx.register_execution_control("tool", runtime.tool_control)
    ctx.register_execution_control("tool_result", runtime.result_control)
    ctx.register_execution_control("llm", runtime.model_control)
    ctx.register_execution_control("auxiliary", runtime.model_control)
    ctx.register_middleware("llm_request", runtime.request_middleware)
    ctx.register_middleware("llm_execution", runtime.model_execution)
    hooks = {
        "on_session_start": runtime.session_start,
        "on_session_end": runtime.session_end,
        "subagent_start": runtime.child_start,
        "pre_llm_call": runtime.pre_model,
        "post_api_request": runtime.post_api,
        "api_request_error": runtime.post_api,
        "post_auxiliary_call": runtime.post_api,

    }
    for event, callback in hooks.items():
        ctx.register_hook(event, callback)
    ctx.on_unload(runtime.roles.stop)

    from bn_gsd.parallel_search import ParallelSearch, SCHEMA
    collector = ParallelSearch(runtime)
    def parallel_search(args, **kw):
        return canonical(collector.run(args, **kw)).decode()
    ctx.register_tool(name="bn_parallel_search",toolset="gsd_native",schema=SCHEMA,handler=parallel_search)

    schema_path = Path(runtime.settings["bundle_root"]) / "adapters/hermes/schemas.json"
    for schema in json.loads(schema_path.read_text()):
        name = schema["name"]
        def handler(args, _name=name, **kw):
            try:
                value = runtime.bridge.engine(_name, args, sid=kw.get("session_id") or "")
                return canonical(value).decode()
            except Exception as exc:
                return canonical({"ok": False, "error": {"code": "GSD_HOST_ERROR", "message": str(exc)}}).decode()
        ctx.register_tool(name=name, toolset="gsd_integration", schema=schema, handler=handler)

    text = {"type": "string", "minLength": 1}
    analyze_schema = {"name": "gsd_analyze", "description": "Настоящие G/S/D, исходное сравнение и ограниченный синтез без внешнего действия.",
        "parameters": {"type": "object", "additionalProperties": False,
            "properties": {"components": {"enum": ["G", "S", "D", "GS", "GD", "SD", "GSD"]},
                           "resume_G_job": text, "corpus_id": text, "request": {"type": "object", "properties": {"scope": text, "question": text},
                                       "required": ["scope", "question"]}, "request_id": text},
            "required": ["components", "request", "request_id"]}}
    work_schema = {"name": "gsd_work", "description": "Исполнить адресную смысловую операцию настоящим G/S/D; отдельно проверить её постусловие.",
        "parameters": {"type": "object", "additionalProperties": False,
            "properties": {"key": text, "corpus_id": text, "inputs": {"type": "object"}, "request_id": text, "run_id": text,
                           "context_profile": {"enum": ["standard", "engineering"]}},
            "required": ["key", "inputs", "request_id"]}}
    status_schema = {"name": "gsd_runtime_status", "description": "Фактическое состояние и общий ресурс семьи: unsettled_provider_attempts — незавершённые обращения; unknown_usage_accounted_attempts и прежний unknown_usage_reservations — уже учтённые обращения с неизвестным расходом, не открытые резервы.",
                     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}
    stop_schema = {"name": "gsd_stop", "description": "Остановить семью GSD и запросить отмену её настоящих дочерних задач.",
                   "parameters": {"type": "object", "properties": {"reason": text},
                                  "required": ["reason"], "additionalProperties": False}}
    def stop(args, sid):
        value = runtime.bridge.call("stop", {"sid": sid, "reason": args["reason"]})
        return {**value, "native_children": runtime.roles.stop(sid)}
    operations = {
        "gsd_research": ({"name": "gsd_research", "description": "Настоящие G/S/D для обычного вопроса: одна область и явные исходные наблюдения; без внешнего действия.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {
                "question": text, "scope": text, "request_id": text, "corpus_id": text, "frame": text, "resume_G_job": text,
                "constraints": {"type": "array", "items": {"type": "string"}},
                "max_candidates": {"type": "integer", "minimum": 1, "maximum": 6},
                "requested_profile": {"enum": ["eMVP", "MVP", "Standard", "eStandard", "High Stakes", "Critical Infrastructure"]},
                "risk": {"type": "object"},
                "observations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "properties": {"id": text, "key": text, "value": {}, "source_id": text, "origin_group": text,
                        "state": {"enum": ["observed", "not_measured", "invalid", "unavailable"]}, "method_valid": {"type": "boolean"}},
                    "required": ["id", "key", "value", "source_id", "origin_group", "state", "method_valid"]}}},
                "required": ["question", "scope", "request_id"]}}, runtime.research),
        "gsd_analyze": (analyze_schema, runtime.analyze),
        "gsd_work": (work_schema, runtime.work),
        "gsd_work_file": ({"name": "gsd_work_file", "description": "Разбить файл независимых записей на адресные операции с полным обязательным контекстом каждой; не делать общий вывод по частям.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {
                "path": text, "sha256": text, "key": text, "request_id": text,
                "interpretation": {"enum": ["independent_records"]},
                "context_profile": {"enum": ["standard", "engineering"]}},
                "required": ["path", "sha256", "key", "request_id", "interpretation"]}}, runtime.work_file),
        "gsd_read_role": ({"name":"gsd_read_role","description":"Читать полный сохранённый продукт завершённой G/S/D роли своей семьи после ошибки доставки, без нового исполнения. Продолжать next_offset до complete. validated — типизированный продукт после привязки доверенным слоем; original — точный видимый исходный текст, не скрытые рассуждения и не байты транспорта.",
            "parameters":{"type":"object","additionalProperties":False,"properties":{
                "job_id":text,"view":{"enum":["validated","original"]},
                "offset":{"type":"integer","minimum":0},"max_chars":{"type":"integer","minimum":1,"maximum":4096}},
                "required":["job_id"]}},runtime.read_role),
        "gsd_runtime_status": (status_schema, lambda args, sid: runtime.bridge.call("family_status", {"sid": sid})),
        "gsd_stop": (stop_schema, stop),
        "gsd_save_artifact": ({"name": "gsd_save_artifact", "description": "Создать один точный текстовый файл по одноразовому разрешению оператора; существующий файл не перезаписывается.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {
                "name": text, "content": {"type": "string"}, "grant_id": text}, "required": ["name", "content", "grant_id"]}},
            lambda args, sid: runtime.bridge.call("artifact", {"sid": sid, "grant_id": args["grant_id"],
                "arguments": {"name": args["name"], "content": args["content"]}})),
    }
    for name, (schema, operation) in operations.items():
        def handler(args, _operation=operation, _schema=schema, **kw):
            try:
                from jsonschema import Draft202012Validator
                Draft202012Validator(_schema["parameters"]).validate(args)
                value = _operation(args, kw.get("session_id") or "")
                return canonical(value).decode()
            except Exception as exc:
                return canonical({"ok": False, "error": {"code": "GSD_NATIVE_ERROR", "message": str(exc)},
                                  "external_effect_performed": False}).decode()
        ctx.register_tool(name=name, toolset="gsd_native", schema=schema, handler=handler)
    for path in sorted((package / "skills").glob("*/SKILL.md")):
        ctx.register_skill(path.parent.name, path)
    def command(raw):
        if raw.strip() in {"", "status"}:
            return canonical(runtime.bridge.engine("gsd_status", {})).decode()
        return "Используйте gsd_analyze, gsd_work, gsd_runtime_status, gsd_stop. Договоры: gsd_catalog и gsd_contract."
    ctx.register_command("gsd", command, description="Версии и действующие интерфейсы GSD")
