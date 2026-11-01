"""Official Undermind MCP for the isolated Hermes BN profile."""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

SERVICE = Path(__file__).resolve().parent
ROOT = SERVICE.parent
sys.path.insert(0, str(ROOT / "hermes-agent"))
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()

WRITES = {
    "create_workspace", "create_folder", "move_folder", "delete_folder",
    "write_file", "move_files", "delete_file", "move_deep_searches", "delete_deep_search",
    "add_papers_to_folder", "remove_papers_from_folder", "star_papers", "unstar_papers",
    "launch_deep_search",
}
INTERNAL = {"get_deep_search_status", "get_paper_pdf_status"}


def content_text(result):
    return "\n".join(x.get("text", "") for x in result.get("content", []) if x.get("type") == "text")


async def download_pdfs(cite_keys, destination):
    import requests
    if not isinstance(cite_keys, list) or not cite_keys or not all(isinstance(k, str) and k for k in cite_keys):
        raise ValueError("Нужен непустой массив cite_keys из текущего рабочего пространства.")
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for key in dict.fromkeys(cite_keys):
        for attempt in range(2):
            response = await run("call", "get_pdf_download_links", {"cite_keys": [key]})
            data = response.get("structuredContent") or {}
            item = next((r for r in data.get("results", []) if r.get("cite_key") == key), None)
            if not item or not item.get("url"):
                records.append({"cite_key": key, "status": "unavailable"})
                break
            url = item["url"]
            if urlsplit(url).scheme != "https":
                raise ValueError("Ожидалась ссылка PDF по HTTPS.")
            with requests.get(url, stream=True, timeout=(15, 60)) as fetched:
                if fetched.status_code == 403 and attempt == 0:
                    continue  # A short-lived link can expire; obtain a new one.
                if not fetched.ok:
                    records.append({"cite_key": key, "status": "download_error", "http_status": fetched.status_code})
                    break
                chunks, size = [], 0
                for chunk in fetched.iter_content(65536):
                    size += len(chunk)
                    if size > 50_000_000:
                        raise ValueError("PDF превышает установленный предел 50 МБ.")
                    chunks.append(chunk)
                content = b"".join(chunks)
            if not content.startswith(b"%PDF"):
                raise ValueError("Скачанный файл не является PDF.")
            filename = Path(item.get("filename") or str(key) + ".pdf").name
            path = destination / filename
            path.write_bytes(content)
            path.chmod(0o600)
            records.append({"cite_key": key, "status": "downloaded", "path": str(path),
                            "bytes": size, "sha256": hashlib.sha256(content).hexdigest()})
            break
    return {"files": records, "temporary_urls_disclosed": False}


async def run(command, name, arguments, confirm_write=False, other_workspace=False):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.exceptions import MCPError
    from jsonschema import Draft202012Validator
    import httpx2
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_oauth_manager import get_manager

    cfg = _load_mcp_config().get("undermind")
    if not cfg or not cfg.get("enabled", True):
        raise ValueError("Undermind ещё не подключён.")
    if cfg.get("url") != "https://mcp.undermind.ai/mcp" or cfg.get("auth") != "oauth":
        raise ValueError("Ожидалось отдельное подключение Undermind через OAuth.")
    auth = get_manager().get_or_build_provider("undermind", cfg["url"], cfg.get("oauth"))
    workspace_file = SERVICE / "config/workspace.json"
    workspace = json.loads(workspace_file.read_text()).get("workspace_id") if workspace_file.exists() else None
    async with httpx2.AsyncClient(auth=auth, timeout=240) as http:
        async with streamable_http_client(cfg["url"], http_client=http) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=240) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                catalog = {t.name: t for t in tools.tools}
                if command == "catalog":
                    prompts = await session.list_prompts() if initialized.capabilities.prompts else None
                    resources = await session.list_resources() if initialized.capabilities.resources else None
                    await session.send_ping()
                    return {"initialize": initialized.model_dump(mode="json", by_alias=True),
                            "tools": tools.model_dump(mode="json", by_alias=True),
                            "prompts": prompts.model_dump(mode="json", by_alias=True) if prompts else None,
                            "resources": resources.model_dump(mode="json", by_alias=True) if resources else None,
                            "ping": "passed"}
                orientation = await session.call_tool("get_orientation", {})
                if command == "orientation" or (command == "call" and name == "get_orientation"):
                    return orientation.model_dump(mode="json", by_alias=True)
                if orientation.is_error:
                    raise ValueError("Undermind не подтвердил подключение; завершите вход.")
                if command == "prompt":
                    result = await session.get_prompt(name, arguments=arguments)
                    return result.model_dump(mode="json", by_alias=True)
                calls = arguments if command == "batch" else [{"name": name, "arguments": arguments}]
                results = []
                for call in calls:
                    tool_name, params = call["name"], dict(call.get("arguments", {}))
                    if tool_name in INTERNAL:
                        raise ValueError("Метод предназначен для виджета. Используйте inspect_deep_searches или get_paper_info.")
                    if tool_name not in catalog:
                        raise ValueError("Инструмент отсутствует в текущем каталоге: " + tool_name)
                    if tool_name in WRITES and not confirm_write:
                        raise ValueError("Создание задания или изменение данных требует задания пользователя и --confirm-write.")
                    schema = catalog[tool_name].input_schema
                    if "workspace_id" in schema.get("properties", {}):
                        if "workspace_id" not in params and workspace:
                            params["workspace_id"] = workspace
                        if workspace and params.get("workspace_id") != workspace and not other_workspace:
                            raise ValueError("Другое рабочее пространство требует явного задания и --other-workspace.")
                    errors = list(Draft202012Validator(schema).iter_errors(params))
                    if errors:
                        raise ValueError("Параметры не соответствуют текущей схеме: " +
                                         "; ".join(e.message for e in errors[:3]))
                    try:
                        result = await session.call_tool(tool_name, arguments=params)
                    except MCPError as e:
                        results.append({"name": tool_name, "mcp_error": e.error.model_dump(mode="json")})
                        return {"ok": False, "calls": results, "same_mcp_session": True}
                    dumped = result.model_dump(mode="json", by_alias=True)
                    results.append({"name": tool_name, "arguments": params, "result": dumped})
                    if result.is_error:
                        return {"ok": False, "calls": results, "same_mcp_session": True}
                if command == "batch":
                    return {"ok": True, "calls": results, "same_mcp_session": True}
                return results[0]["result"]


def main():
    parser = argparse.ArgumentParser(prog="undermind-bn", description="Undermind для независимого Hermes BN.")
    parser.add_argument("command", choices=["catalog", "orientation", "call", "batch", "prompt", "profiles", "workspace", "download"])
    parser.add_argument("--name")
    parser.add_argument("--profile")
    parser.add_argument("--params", type=Path, help="JSON с параметрами инструмента или массивом вызовов")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-write", action="store_true")
    parser.add_argument("--other-workspace", action="store_true")
    parser.add_argument("--download-dir", type=Path, default=SERVICE / "downloads")
    args = parser.parse_args()
    params = json.loads(args.params.read_text()) if args.params else {}
    profiles_file = SERVICE / "config/profiles.json"
    profiles = json.loads(profiles_file.read_text()) if profiles_file.exists() else {}
    if args.profile:
        if args.profile not in profiles:
            parser.error("Неизвестная конфигурация.")
        preset = profiles[args.profile]
        args.command, args.name = preset["command"], preset["name"]
        params = {**preset.get("arguments", {}), **params}
    try:
        if args.command == "profiles":
            result = profiles
        elif args.command == "workspace":
            result = json.loads((SERVICE / "config/workspace.json").read_text())
        elif args.command == "download":
            result = asyncio.run(download_pdfs(params.get("cite_keys", []), args.download_dir))
        else:
            result = asyncio.run(run(args.command, args.name, params, args.confirm_write, args.other_workspace))
    except Exception as e:
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        if isinstance(e, ValueError):
            message = str(e)
        elif getattr(e, "error", None) is not None and hasattr(e.error, "model_dump"):
            message = json.dumps(e.error.model_dump(mode="json"), ensure_ascii=False)
        else:
            message = "Ошибка Undermind: " + type(e).__name__
        parser.exit(2, message + "\n")
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        args.output.chmod(0o600)
        print(str(args.output))
    else:
        print(text, end="")
    if isinstance(result, dict) and result.get("ok") is False:
        sys.exit(2)


if __name__ == "__main__":
    main()
