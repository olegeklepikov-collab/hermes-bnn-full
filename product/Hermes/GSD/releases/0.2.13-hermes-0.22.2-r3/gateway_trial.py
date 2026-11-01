#!/usr/bin/env python3
"""One real loopback gateway request; never retries or sends to a messaging platform."""
from pathlib import Path
import json
import urllib.request

WORK = Path(__file__).resolve().parent.parent
port = json.loads((WORK / "lab-operator/gateway-test.json").read_text())["port"]
key = next(line.split("=", 1)[1] for line in (WORK / "lab-home/.env").read_text().splitlines()
           if line.startswith("API_SERVER_KEY="))
body = {"model": "hermes-agent", "input": (WORK / "results/semantic-query-3.txt").read_text(),
        "store": True, "conversation": "gsd-semantic-independent-3", "stream": False}
request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/responses", data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=600) as response:
    raw = json.loads(response.read())
    # Keep observable products, never inspect or distribute hidden reasoning fields.
    safe = {k: v for k, v in raw.items() if k in {"id", "object", "status", "model", "usage", "error", "created_at"}}
    safe["output"] = [{k: v for k, v in item.items() if k not in {"reasoning_content", "reasoning", "summary"}}
                      for item in raw.get("output", []) if item.get("type") != "reasoning"]
    (WORK / "results/semantic-gateway-3.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    print(json.dumps({"http_status": response.status, "response_id": safe.get("id"),
                      "status": safe.get("status"), "observable_items": len(safe["output"])}, ensure_ascii=False))
