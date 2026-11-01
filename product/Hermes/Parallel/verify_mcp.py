"""Exercise all six remote MCP operations using two small public-source jobs."""
import asyncio
import json
import re
import time
from pathlib import Path
import httpx2
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]
REPORT = json.loads((OUT / "mcp-report.json").read_text()) if (OUT / "mcp-report.json").exists() else {}
REPORT.pop("error_1", None)

def save(n, d):
    p = OUT / (n + ".json"); p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n"); p.chmod(0o600)

def text_of(d):
    return "\n".join(x.get("text", "") for x in d.get("content", []))

async def call(s, name, args, label):
    result = await s.call_tool(name, args)
    d = result.model_dump(mode="json", by_alias=True); save(label, d)
    assert not d.get("isError"), text_of(d)[:1000]
    return d

async def search():
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + KEY}, timeout=90.0) as h:
        async with streamable_http_client("https://search.parallel.ai/mcp?mode=fast", http_client=h) as st:
            async with ClientSession(st[0], st[1], read_timeout_seconds=90.0) as s:
                await s.initialize()
                d = await call(s, "web_search", {"objective": "Find official Parallel Search modes and pricing documentation.",
                    "search_queries": ["Parallel Search modes pricing"]}, "mcp-web-search")
                assert "docs.parallel.ai" in json.dumps(d)
                match = re.search(r'"session_id"\s*:\s*"([^"\\]+)', json.dumps(d.get("structuredContent") or {}))
                args = {"urls": ["https://docs.parallel.ai/getting-started/pricing"], "full_content": True,
                        "objective": "Read the official pricing units for Search and Extract."}
                if match: args["session_id"] = match.group(1)
                d = await call(s, "web_fetch", args, "mcp-web-fetch")
                assert "Pricing" in json.dumps(d) and "Extract" in json.dumps(d)
                REPORT["search_mcp"] = {"passed": True, "operations": ["web_search", "web_fetch"]}
                save("mcp-report", REPORT); print("Search MCP passed", flush=True)

async def task():
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + KEY}, timeout=180.0) as h:
        async with streamable_http_client("https://task-mcp.parallel.ai/mcp", http_client=h) as st:
            async with ClientSession(st[0], st[1], read_timeout_seconds=180.0) as s:
                await s.initialize()
                research_file = OUT / "mcp-research-created.json"
                group_file = OUT / "mcp-group-created.json"
                research = json.loads(research_file.read_text()) if research_file.exists() else await call(s, "createDeepResearch", {"input":
                    "Read https://docs.parallel.ai/search/modes and https://docs.parallel.ai/getting-started/pricing. In Russian, name the four current Search modes and Search/Extract pricing units. Use only official Parallel docs. Limit the report to 150 words and cite sources.",
                    "processor": "pro", "source_policy": {"include_domains": ["docs.parallel.ai"]}}, "mcp-research-created")
                group = json.loads(group_file.read_text()) if group_file.exists() else await call(s, "createTaskGroup", {"inputs": [
                    {"api": "Search", "url": "https://docs.parallel.ai/getting-started/pricing"},
                    {"api": "Extract", "url": "https://docs.parallel.ai/getting-started/pricing"}],
                    "output_type": "json", "output": "For each input return api, billing_unit, fast_or_standard_usd_per_1000 as a number, source_url. Search uses fast mode; Extract price is per 1000 URLs. Read only official pricing.",
                    "processor": "base", "source_policy": {"include_domains": ["docs.parallel.ai"]}}, "mcp-group-created")
                ids = []
                for name, d, prefix in [("research", research, "trun"), ("group", group, "tgrp")]:
                    found = re.search(prefix + r"_[A-Za-z0-9_-]+", text_of(d) + json.dumps(d.get("structuredContent") or {}))
                    assert found, "No run identifier returned"
                    ids.append((name, found.group(0)))
                REPORT["task_ids"] = dict(ids); save("mcp-report", REPORT)
                print("Task MCP jobs created", dict(ids), flush=True)
                remaining = dict(ids); deadline = time.monotonic() + 900
                while remaining and time.monotonic() < deadline:
                    for name, run_id in list(remaining.items()):
                        d = await call(s, "getStatus", {"taskRunOrGroupId": run_id}, "mcp-" + name + "-status")
                        status = d.get("structuredContent") or json.loads(text_of(d))
                        if status.get("status") in ["failed", "cancelled"] or status.get("failed", 0):
                            raise RuntimeError(name + " ended with failure: " + json.dumps(status))
                        completed = status.get("status") == "completed" or (
                            status.get("is_active") is False and status.get("total") == status.get("completed") and status.get("total", 0) > 0)
                        if completed:
                            args = {"taskRunOrGroupId": run_id}
                            if name == "group": args["basis"] = "all"
                            result = await call(s, "getResultMarkdown", args, "mcp-" + name + "-result")
                            assert "docs.parallel.ai" in json.dumps(result)
                            REPORT[name] = {"passed": True, "id": run_id}; save("mcp-report", REPORT)
                            del remaining[name]; print(name, "completed", flush=True)
                    if remaining: await asyncio.sleep(20)
                assert not remaining, "Jobs still running; retain identifiers for later polling"
                REPORT["task_mcp"] = {"passed": True, "operations": ["createDeepResearch", "createTaskGroup", "getStatus", "getResultMarkdown"]}
                save("mcp-report", REPORT)

async def main():
    operations = [task()]
    if not REPORT.get("search_mcp", {}).get("passed"): operations.append(search())
    outcomes = await asyncio.gather(*operations, return_exceptions=True)
    for i, result in enumerate(outcomes):
        if isinstance(result, BaseException): REPORT["error_" + str(i)] = type(result).__name__ + ": " + str(result)[:1000]
    save("mcp-report", REPORT); print(REPORT, flush=True)

if __name__ == "__main__": asyncio.run(main())
