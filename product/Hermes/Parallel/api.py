"""Small authenticated adapter for documented endpoints absent from the CLI."""
import argparse
import json
from pathlib import Path
import httpx


def main(argv, key, defaults=None):
    p = argparse.ArgumentParser(prog="parallel-bn api")
    p.add_argument("method", choices=["GET", "POST", "PATCH"])
    p.add_argument("path", help="Documented API path; never a URL")
    p.add_argument("--body", type=Path, help="JSON request file")
    p.add_argument("--output", type=Path)
    p.add_argument("--stream", action="store_true")
    p.add_argument("--timeout", type=float, default=120)
    a = p.parse_args(argv)
    if not key:
        p.error("Сохраните Parallel API key в Hermes BN.")
    if not a.path.startswith(("/v1/", "/v1beta/findall/", "/v1alpha/monitors")) or ".." in a.path or "://" in a.path:
        p.error("Нужен документированный путь API данных Parallel.")
    body = json.loads(a.body.read_text()) if a.body else None
    if defaults:
        def merge(base, extra):
            out = dict(base)
            for k, v in extra.items():
                out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
            return out
        body = merge(defaults, body or {})
    if a.stream and a.path == "/v1/responses":
        body = {**(body or {}), "stream": True}
    headers = {"x-api-key": key, "Authorization": "Bearer " + key}
    with httpx.Client(base_url="https://api.parallel.ai", headers=headers,
                      timeout=a.timeout, follow_redirects=False) as c:
        if a.stream:
            with c.stream(a.method, a.path, json=body) as r:
                r.raise_for_status()
                text = "\n".join(r.iter_lines()) + "\n"
        else:
            r = c.request(a.method, a.path, json=body)
            r.raise_for_status()
            text = json.dumps(r.json(), ensure_ascii=False, indent=2) + "\n"
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text)
        a.output.chmod(0o600)
        print(str(a.output))
    else:
        print(text, end="")
