"""Run the official Parallel CLI with Hermes BN credentials and disk paths."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from dotenv import dotenv_values

os.environ.pop("PARALLEL_API_KEY", None)
os.environ["PARALLEL_API_URL"] = "https://api.parallel.ai"
os.environ["PARALLEL_BASE_URL"] = "https://api.parallel.ai"
os.environ["PARALLEL_PLATFORM_URL"] = "https://platform.parallel.ai"
os.environ["PARALLEL_SERVICE_API_URL"] = "https://api.parallel.ai/account"
key = dotenv_values(ROOT / "data/.env").get("PARALLEL_API_KEY")
if key:
    os.environ["PARALLEL_API_KEY"] = key
os.environ["PARALLEL_SKILLS_GLOBAL_DIR"] = str(ROOT / "data/skills")

from parallel_web_tools.core import credentials
from parallel_web_tools.cli import updater

credentials.AUTH_FILE = ROOT / "Parallel/config/auth.json"
credentials.CREDENTIALS_FILE = credentials.AUTH_FILE
credentials.LEGACY_CREDENTIALS_FILE = ROOT / "Parallel/config/credentials.json"
updater.CONFIG_DIR = ROOT / "Parallel/config"
updater.CONFIG_FILE = updater.CONFIG_DIR / "cli.json"
updater.UPDATE_STATE_FILE = updater.CONFIG_DIR / "update-state.json"

if len(sys.argv) > 1 and sys.argv[1] == "profile":
    import json
    profiles = json.loads((ROOT / "Parallel/config/profiles.json").read_text())
    if len(sys.argv) < 3 or sys.argv[2] not in profiles:
        print("Доступные конфигурации: " + ", ".join(profiles))
        raise SystemExit(0 if len(sys.argv) < 3 else 2)
    profile = profiles[sys.argv[2]]
    from api import main
    main([profile["method"], profile["path"], *sys.argv[3:]], key, profile["body"])
elif len(sys.argv) > 1 and sys.argv[1] == "api":
    from api import main
    main(sys.argv[2:], key)
else:
    scoped_commands = {("research", "run"), ("findall", "run"),
                       ("monitor", "create"), ("memory", "retrieve")}
    if tuple(sys.argv[1:3]) in scoped_commands and not any(
        arg == flag or arg.startswith(flag + "=")
        for arg in sys.argv[3:] for flag in ("--memory-scope-key", "--scope-key")
    ):
        sys.argv.extend(["--memory-scope-key", "hermes-bn"])
    # The official CLI loads .env.local at import. Import in the instance directory.
    previous_cwd = Path.cwd()
    os.chdir(ROOT / "Parallel")
    from parallel_web_tools.cli import main
    os.chdir(previous_cwd)
    main(prog_name="parallel-bn")
