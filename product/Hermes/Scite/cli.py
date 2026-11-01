"""Scite for the isolated Hermes BN profile; official MCP and OpenAPI only."""
import argparse
import asyncio
import csv
import io
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

SERVICE = Path(__file__).resolve().parent
ROOT = SERVICE.parent
sys.path.insert(0, str(ROOT / "hermes-agent"))
from hermes_cli.env_loader import load_hermes_dotenv
from agent.secret_scope import get_secret

load_hermes_dotenv()
SPEC = json.loads((SERVICE / "источники/rest-openapi.json").read_text())
OPERATIONS = {
    op["operationId"]: (method.upper(), path, op)
    for path, entries in SPEC["paths"].items()
    for method, op in entries.items()
    if method in {"get", "post", "put", "patch", "delete"}
}
MCP_WRITES = {
    "create_collection", "update_collection", "delete_collection",
    "add_dois_to_collection", "remove_dois_from_collection",
    "create_collection_note", "update_collection_note", "delete_collection_note",
    "upload_collection_file", "delete_collection_file", "manage_subscription",
}
READ_POSTS = {
    "getPapersBulk", "getTalliesBulk", "getSectionTalliesBulk",
    "getAggregateTally", "getJournalIndexBulk",
} | {k for k in OPERATIONS if k.endswith("Facets")}


def validate(value, schema):
    from jsonschema import Draft202012Validator
    schema = {**schema, "components": SPEC["components"]}
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError("Параметры не соответствуют официальной схеме: " +
                         "; ".join("/".join(map(str, e.path)) + ": " + e.message for e in errors[:5]))


def export_saved(path, output_format):
    value = json.loads(path.read_text())
    if "calls" in value:
        value = next(c["result"] for c in value["calls"] if c.get("name") == "search_literature" and "result" in c)
    if isinstance(value.get("content"), list):
        value = json.loads(next(c["text"] for c in value["content"] if c["type"] == "text"))
    elif "result" in value:
        value = value["result"]
    if output_format in {"bibtex", "ris"}:
        if value.get("format") != output_format:
            raise ValueError("Формат исходной библиографии не совпадает с запрошенным.")
        text = value["content"]
        if output_format == "bibtex":
            return re.sub(r"(?m)^@journal-article\{", "@article{", text)
        return re.sub(r"(?m)^\d+\.\s*\n(?=TY\s+-)", "", text)
    records = value.get("hits", value.get("papers"))
    if records is None and "doi" in value:
        records = [value]
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        raise ValueError("В файле нет полученных сведений о публикациях.")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["doi", "title", "authors", "journal", "year", "date"])
    writer.writeheader()
    for record in records:
        authors = record.get("authors", [])
        if isinstance(authors, list):
            authors = "; ".join(str(a.get("authorName", a.get("name", ""))) if isinstance(a, dict) else str(a) for a in authors)
        writer.writerow({**{k: record.get(k, "") for k in ["doi", "title", "journal", "year", "date"]}, "authors": authors})
    return buffer.getvalue()


def rest_call(operation, args, body, confirm_write=False, evaluation=False):
    import requests
    if operation not in OPERATIONS:
        raise ValueError("Неизвестная операция; используйте rest-operations.")
    method, path, op = OPERATIONS[operation]
    readonly = (method == "GET" and operation != "cancelReferenceCheckTask") or operation in READ_POSTS
    if not readonly and not confirm_write:
        raise ValueError("Изменение данных требует явного задания пользователя и --confirm-write.")
    policy = json.loads((SERVICE / "config/policy.json").read_text())
    if operation == "searchPublications" and not (evaluation or policy.get("rest_search_licensed")):
        raise ValueError("Прямой Search API требует отдельной лицензии. Используйте MCP; --evaluation допустим для проверки подключения.")
    parameters = {p["name"]: p for p in op.get("parameters", []) if p["in"] != "header"}
    unknown = set(args) - set(parameters)
    if unknown:
        raise ValueError("Неизвестные параметры: " + ", ".join(sorted(unknown)))
    query = {}
    for name, p in parameters.items():
        if name not in args:
            if p.get("required"):
                raise ValueError("Не задан обязательный параметр: " + name)
            continue
        value = args[name]
        validate(value, p.get("schema", {}))
        if p["in"] == "path":
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        elif p["in"] == "query":
            if isinstance(value, bool):
                value = str(value).lower()
            query[name] = value
    request = op.get("requestBody", {})
    if body is not None:
        schema = request.get("content", {}).get("application/json", {}).get("schema")
        if schema is None:
            raise ValueError("Эта операция не принимает JSON; используйте официальный способ отправки файла.")
        validate(body, schema)
        if operation in READ_POSTS and isinstance(body, list) and len(body) > 500:
            raise ValueError("Предел пакетной обработки: 500 DOI.")
    elif request.get("required"):
        raise ValueError("Нужно JSON-тело запроса: --body-file.")
    public = op.get("security") == []
    key = None if public else get_secret("MCP_SCITE_API_KEY")
    if not public and not key:
        raise ValueError("Ключ Scite ещё не сохранён в Hermes BN.")
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    for attempt in range(3 if readonly else 1):
        response = requests.request(method, "https://api.scite.ai" + path, params=query,
                                    json=body, headers=headers, timeout=(15, 60), allow_redirects=False)
        if response.status_code not in {429, 502, 503, 504} or attempt == 2 or not readonly:
            break
        delay = response.headers.get("Retry-After", response.headers.get("RateLimit-Reset"))
        try:
            seconds = float(delay) if delay is not None else 2 ** attempt + random.random()
        except ValueError:
            seconds = 2 ** attempt + random.random()
        if seconds > 30:
            break
        time.sleep(max(0, seconds))
    try:
        data = response.json()
    except ValueError:
        data = {"message": "Ответ не в формате JSON", "bytes": len(response.content)}
    rates = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
    result = {"operation": operation, "http_status": response.status_code,
              "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "rate_limits": rates, "result": data}
    if not response.ok:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


async def mcp_call(command, name, arguments, confirm_write=False):
    from mcp import ClientSession
    from mcp.shared.exceptions import MCPError
    from mcp.client.streamable_http import streamable_http_client
    import httpx2
    from tools.mcp_tool_config import _load_mcp_config
    cfg = _load_mcp_config().get("scite")
    if not cfg or not cfg.get("enabled", True):
        raise ValueError("Подключение Scite ожидает входа; сервер пока отключён.")
    if cfg.get("url") != "https://api.scite.ai/mcp":
        raise ValueError("Неожиданный адрес сервера Scite.")
    auth = None
    if cfg.get("auth") == "oauth":
        from tools.mcp_oauth_manager import get_manager
        auth = get_manager().get_or_build_provider("scite", cfg["url"], cfg.get("oauth"))
    elif not get_secret("MCP_SCITE_API_KEY"):
        raise ValueError("Ключ Scite ещё не сохранён в Hermes BN.")
    async with httpx2.AsyncClient(headers=cfg.get("headers", {}), auth=auth, timeout=90) as http:
        async with streamable_http_client(cfg["url"], http_client=http) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=90) as session:
                initialized = await session.initialize()
                if command == "catalog":
                    tools = await session.list_tools()
                    prompts = await session.list_prompts()
                    resources = await session.list_resources()
                    await session.send_ping()
                    return {"initialize": initialized.model_dump(mode="json", by_alias=True),
                            "tools": tools.model_dump(mode="json", by_alias=True),
                            "prompts": prompts.model_dump(mode="json", by_alias=True),
                            "resources": resources.model_dump(mode="json", by_alias=True), "ping": "ok"}
                if command == "prompt":
                    result = await session.get_prompt(name, arguments=arguments)
                else:
                    tools = await session.list_tools()
                    calls = arguments if command == "batch" else [{"name": name, "arguments": arguments}]
                    results = []
                    for call in calls:
                        tool_name, params = call["name"], call.get("arguments", {})
                        writes = tool_name in MCP_WRITES
                        if tool_name == "manage_subscription":
                            writes = "pay_as_you_go_limit" in params
                        if writes and not confirm_write:
                            raise ValueError("Изменение данных требует явного задания пользователя и --confirm-write.")
                        tool = next((t for t in tools.tools if t.name == tool_name), None)
                        if tool is None:
                            raise ValueError("Инструмент отсутствует в текущем каталоге: " + tool_name)
                        unknown = set(params) - set(tool.input_schema.get("properties", {}))
                        if unknown:
                            raise ValueError("Неизвестные параметры: " + ", ".join(sorted(unknown)))
                        validate(params, tool.input_schema)
                        try:
                            result = await session.call_tool(tool_name, arguments=params)
                        except MCPError as e:
                            error = e.error.model_dump(mode="json", by_alias=True)
                            results.append({"name": tool_name, "mcp_error": error})
                            return {"calls": results, "ok": False, "same_mcp_session": True}
                        results.append({"name": tool_name, "result": result.model_dump(mode="json", by_alias=True)})
                        if getattr(result, "is_error", False):
                            return {"calls": results, "ok": False, "same_mcp_session": True}
                    if command == "batch":
                        return {"calls": results, "same_mcp_session": True}
                return result.model_dump(mode="json", by_alias=True)


def main():
    p = argparse.ArgumentParser(prog="scite-bn", description="Scite в независимом Hermes BN.")
    p.add_argument("command", choices=["profiles", "rest-operations", "rest", "catalog", "call", "batch", "prompt", "export"])
    p.add_argument("--name", help="Имя операции, инструмента или шаблона")
    p.add_argument("--profile")
    p.add_argument("--params", type=Path, help="JSON с параметрами, без ключей")
    p.add_argument("--body-file", type=Path)
    p.add_argument("--from-file", type=Path, help="Сохранённый ответ Scite для местной выгрузки")
    p.add_argument("--export-format", choices=["csv", "bibtex", "ris"], default="csv")
    p.add_argument("--confirm-write", action="store_true")
    p.add_argument("--evaluation", action="store_true")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    profiles = json.loads((SERVICE / "config/profiles.json").read_text())
    params = json.loads(a.params.read_text()) if a.params else {}
    if a.profile:
        if a.profile not in profiles:
            p.error("Неизвестная конфигурация.")
        preset = profiles[a.profile]
        a.command, a.name = preset["command"], preset["name"]
        params = {**preset.get("arguments", {}), **params}
    try:
        if a.command == "export":
            if not a.from_file:
                raise ValueError("Нужен --from-file со сведениями, полученными из Scite.")
            result = export_saved(a.from_file, a.export_format)
        elif a.command == "profiles":
            result = profiles
        elif a.command == "rest-operations":
            result = {k: {"method": v[0], "path": v[1], "description": v[2].get("summary")} for k, v in OPERATIONS.items()}
        elif a.command == "rest":
            body = json.loads(a.body_file.read_text()) if a.body_file else None
            result = rest_call(a.name, params, body, a.confirm_write, a.evaluation)
        else:
            result = asyncio.run(mcp_call(a.command, a.name, params, a.confirm_write))
    except Exception as e:
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        if isinstance(e, (ValueError, RuntimeError)):
            message = str(e)
        elif getattr(e, "error", None) is not None and hasattr(e.error, "model_dump"):
            message = json.dumps(e.error.model_dump(mode="json"), ensure_ascii=False)
        else:
            message = "Ошибка подключения Scite: " + type(e).__name__
        p.exit(2, message + "\n")
    text = result if a.command == "export" else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text)
        a.output.chmod(0o600)
        print(str(a.output))
    else:
        print(text, end="")
    if isinstance(result, dict) and result.get("ok") is False:
        sys.exit(2)


if __name__ == "__main__":
    main()
