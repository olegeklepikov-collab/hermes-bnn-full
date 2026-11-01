"""Official alphaXiv MCP through independent Hermes BN OAuth."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parent
ROOT = SERVICE.parent
sys.path.insert(0, str(ROOT / "hermes-agent"))
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()

WRITES = {"create_folder", "rename_folder", "save_papers_to_folder", "remove_papers_from_folder",
          "move_papers_between_folders", "follow_researcher", "unfollow_researcher", "edit_private_paper_metadata"}

async def run(command, name, params, confirm_write=False, other_library=False, following=False):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.exceptions import MCPError
    from jsonschema import Draft202012Validator
    import httpx2
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_oauth_manager import get_manager
    cfg = _load_mcp_config().get("alphaxiv")
    if not cfg or not cfg.get("enabled", True) or cfg.get("url") != "https://api.alphaxiv.org/mcp/v1" or cfg.get("auth") != "oauth":
        raise ValueError("Нужен независимый вход alphaXiv в Hermes BN.")
    auth = get_manager().get_or_build_provider("alphaxiv", cfg["url"], cfg.get("oauth"))
    async with httpx2.AsyncClient(auth=auth, timeout=240) as http:
        async with streamable_http_client(cfg["url"], http_client=http) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=240) as session:
                init = await session.initialize()
                listing = await session.list_tools()
                catalog = {t.name: t for t in listing.tools}
                if command == "catalog":
                    prompts = await session.list_prompts() if init.capabilities.prompts else None
                    resources = await session.list_resources() if init.capabilities.resources else None
                    await session.send_ping()
                    return {"initialize": init.model_dump(mode="json", by_alias=True),
                            "tools": listing.model_dump(mode="json", by_alias=True),
                            "prompts": prompts.model_dump(mode="json", by_alias=True) if prompts else None,
                            "resources": resources.model_dump(mode="json", by_alias=True) if resources else None,
                            "ping": "passed"}
                calls = params if command == "batch" else [{"name": name, "arguments": params}]
                library_path = SERVICE / "config/library.json"
                library = json.loads(library_path.read_text()) if library_path.exists() else {}
                folders = set(library.get("folder_ids", {}).values())
                prepared = []
                for item in calls:
                    n, args = item["name"], dict(item.get("arguments", {}))
                    if n not in catalog:
                        raise ValueError("Нет метода в действующем каталоге: " + str(n))
                    if n == "delete_folder":
                        raise ValueError("Удаление папки не входит в настроенные операции. Требуется отдельное решение владельца.")
                    if n in WRITES and not confirm_write:
                        raise ValueError("Изменение библиотеки требует задания пользователя и --confirm-write.")
                    if n in {"follow_researcher", "unfollow_researcher"} and not following:
                        raise ValueError("Изменение подписок требует отдельного задания и --allow-following.")
                    if n in WRITES and not other_library:
                        for key in ["folder_id", "from_folder_id", "to_folder_id", "parent_folder_id"]:
                            if args.get(key) and args[key] not in folders:
                                raise ValueError("Папка вне библиотеки Hermes BN требует --other-library и отдельного задания.")
                        if n == "save_papers_to_folder" and not args.get("folder_id"):
                            raise ValueError("Укажите собственную папку Hermes BN, без записи в папку по умолчанию.")
                    errors = list(Draft202012Validator(catalog[n].input_schema).iter_errors(args))
                    if errors:
                        raise ValueError("Параметры не соответствуют схеме: " + "; ".join(e.message for e in errors[:3]))
                    prepared.append((n, args))
                results = []
                for n, args in prepared:
                    try:
                        result = await session.call_tool(n, arguments=args)
                    except MCPError as e:
                        return {"ok": False, "calls": results, "name": n, "mcp_error": e.error.model_dump(mode="json")}
                    dumped = result.model_dump(mode="json", by_alias=True)
                    if command != "batch":
                        return dumped
                    results.append({"name": n, "arguments": args, "result": dumped})
                    if result.is_error:
                        return {"ok": False, "calls": results}
                return {"ok": True, "calls": results, "same_mcp_session": True}


def main():
    p = argparse.ArgumentParser(prog="alphaxiv-bn", description="alphaXiv для независимого Hermes BN.")
    p.add_argument("command", choices=["catalog", "call", "batch", "profiles", "library"])
    p.add_argument("--name"); p.add_argument("--profile")
    p.add_argument("--params", type=Path); p.add_argument("--output", type=Path)
    p.add_argument("--confirm-write", action="store_true")
    p.add_argument("--other-library", action="store_true")
    p.add_argument("--allow-following", action="store_true")
    args = p.parse_args()
    profiles_path = SERVICE / "config/profiles.json"
    profiles = json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
    params = json.loads(args.params.read_text()) if args.params else {}
    if args.profile:
        if args.profile not in profiles: p.error("Неизвестная конфигурация.")
        preset = profiles[args.profile]
        args.command, args.name = preset["command"], preset["name"]
        params = {**preset.get("arguments", {}), **params}
    try:
        if args.command == "profiles": result = profiles
        elif args.command == "library": result = json.loads((SERVICE / "config/library.json").read_text())
        else: result = asyncio.run(run(args.command, args.name, params, args.confirm_write, args.other_library, args.allow_following))
    except Exception as e:
        while isinstance(e, BaseExceptionGroup) and e.exceptions: e = e.exceptions[0]
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr); sys.exit(2)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text); args.output.chmod(0o600)
        print(str(args.output))
    else: print(text, end="")
    if isinstance(result, dict) and (result.get("ok") is False or result.get("isError")): sys.exit(2)

if __name__ == "__main__": main()
