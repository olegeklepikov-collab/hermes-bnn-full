"""Only fixed, operator-configured subprocesses can enter the supplied engine."""
from pathlib import Path
import json
import subprocess
from .codec import canonical, read_json


class Bridge:
    def __init__(self, settings_path):
        self.settings_path = Path(settings_path).resolve()
        self.settings = read_json(self.settings_path.read_text())
        self.worker = Path(__file__).resolve().parents[1] / "worker.py"

    def call(self, operation, arguments=None):
        payload = canonical({"operation": operation, "arguments": arguments or {}})
        if len(payload) > 24 * 1024 * 1024:
            raise ValueError("Input exceeds contract; split the task without trimming required data")
        from tools.environments.local import served_profile_child_env
        from hermes_constants import get_hermes_home
        env = served_profile_child_env(target_home=get_hermes_home(), inherit_credentials=False)
        env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([self.settings["python"], "-I", "-B", str(self.worker),
                                 "--settings", str(self.settings_path)], input=payload,
                                capture_output=True, timeout=180, env=env, cwd=self.settings["state_dir"])
        if len(result.stdout) > 24 * 1024 * 1024:
            raise ValueError("Worker output exceeds contract; it was not truncated")
        value = read_json(result.stdout)
        if result.returncode or value.get("ok") is not True:
            error = value.get("error", {})
            raise ValueError(error.get("message", "GSD host worker failed"))
        return value["result"]

    def engine(self, tool, arguments, provider_config=None, sid=None):
        return self.call("model_engine" if sid else "engine", {"tool": tool, "arguments": arguments,
                                    "provider_config": provider_config, **({"sid": sid} if sid else {})})
