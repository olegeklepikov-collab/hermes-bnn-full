"""Repeat the two-row check with an exact page allowlist and billing context."""
import asyncio
import json
import re
from pathlib import Path
import httpx2
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]

def save(name, d):
    p = OUT / (name + ".json"); p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n"); p.chmod(0o600)

async def call(s, name, args, label):
    d = (await s.call_tool(name, args)).model_dump(mode="json", by_alias=True); save(label, d)
    assert not d.get("isError"), str(d)[:1000]
    text = "\n".join(x.get("text", "") for x in d.get("content", []))
    return d, text

async def main():
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + KEY}, timeout=180) as h:
        async with streamable_http_client("https://task-mcp.parallel.ai/mcp", http_client=h) as st:
            async with ClientSession(st[0], st[1], read_timeout_seconds=180) as s:
                f = OUT / "mcp-group-scoped-created.json"
                if f.exists(): d = json.loads(f.read_text()); text = "\n".join(x.get("text", "") for x in d["content"])
                else:
                    d, text = await call(s, "createTaskGroup", {"inputs": [
                        {"api": "Search", "mode": "fast", "billing_context": "Regular API-key access to api.parallel.ai, NOT the MPP/x402 payments gateway", "source_url": "https://docs.parallel.ai/getting-started/pricing"},
                        {"api": "Extract", "billing_context": "Regular API-key access to api.parallel.ai, NOT the MPP/x402 payments gateway", "source_url": "https://docs.parallel.ai/getting-started/pricing"}],
                        "output_type": "json", "output": "Return api, usd_per_1000 (number or null), billing_unit, source_url. Read ONLY the source_url provided. Use the Search fast table or the Extract API table on that page. Exclude MPP/x402, agentic-payments and parallelmpp.dev prices. Copy source_url exactly from input. Unknown or conflicting data must be null.",
                        "processor": "core", "source_policy": {"include_domains": ["docs.parallel.ai/getting-started/pricing"]}}, "mcp-group-scoped-created")
                match = re.search(r"tgrp_[A-Za-z0-9_-]+", text); assert match; run_id = match.group(0)
                print("Scoped group", run_id, flush=True)
                for _ in range(40):
                    _, text = await call(s, "getStatus", {"taskRunOrGroupId": run_id}, "mcp-group-scoped-status")
                    status = json.loads(text)
                    assert status.get("failed", 0) == 0
                    if status.get("is_active") is False and status.get("completed") == 2: break
                    await asyncio.sleep(20)
                else: raise RuntimeError("Group still running; resume saved ID")
                _, text = await call(s, "getResultMarkdown", {"taskRunOrGroupId": run_id, "basis": "all"}, "mcp-group-scoped-result")
                print("Scoped group completed; validate structured SDK output next", flush=True)

if __name__ == "__main__": asyncio.run(main())
