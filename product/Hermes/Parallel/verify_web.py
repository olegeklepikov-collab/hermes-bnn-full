"""Bounded live checks against public sources; never logs credentials."""
import asyncio
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import sys
import threading
import httpx
from dotenv import dotenv_values
from parallel import Parallel
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]
os.environ["PARALLEL_API_KEY"] = KEY
REPORT = {}; LOCK = threading.Lock()

def save(name, data):
    f = OUT / (name + ".json")
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n"); f.chmod(0o600)

def check(name, fn):
    try:
        data, evidence = fn(); save(name, data)
        row = {"passed": True, "evidence": evidence}
    except Exception as e:
        row = {"passed": False, "error": type(e).__name__ + ": " + str(e)[:1000]}
    with LOCK:
        REPORT[name] = row; save("web-report", REPORT)
        print(name, row, flush=True)

def search(mode):
    with Parallel(api_key=KEY, max_retries=0, timeout=75) as c:
        settings = {"max_results": 3}
        if mode != "turbo": settings["source_policy"] = {"include_domains": ["docs.parallel.ai/search"]}
        r = c.search(mode=mode, objective="Find official current Parallel Search API modes and usage instructions.",
                     search_queries=["Parallel Search API modes"], max_chars_total=5000, advanced_settings=settings)
        d = r.model_dump(mode="json")
        assert d["results"] and all(x.get("url") for x in d["results"])
        return d, {"results": len(d["results"]), "session_id": d["session_id"]}

def extract(full):
    urls = ["https://docs.parallel.ai/getting-started/pricing", "https://arxiv.org/pdf/2005.11401"] if full else [
        "https://docs.parallel.ai/getting-started/pricing", "https://example.com/parallel-bn-missing-page-20261006"]
    with Parallel(api_key=KEY, max_retries=0, timeout=90) as c:
        r = c.extract(urls=urls, objective="Find pricing or the paper title and original research method.",
                      max_chars_total=20000, advanced_settings={"full_content": full})
        d = r.model_dump(mode="json")
        assert d["results"]
        if full:
            assert len(d["results"]) == 2 and all(x.get("full_content") for x in d["results"])
            assert "retrieval" in json.dumps(d).lower()
        else: assert d["errors"]
        return d, {"results": len(d["results"]), "per_url_errors": len(d["errors"])}

def response(effort, structured=False):
    with OpenAI(api_key=KEY, base_url="https://api.parallel.ai/v1", max_retries=0, timeout=150) as c:
        args = {"model": "parallel", "input": "По официальной документации Parallel назовите четыре текущих режима Search и цену fast за один запрос. Ответьте по-русски с источниками.",
                "reasoning": {"effort": effort}, "tools": [{"type": "web_search", "filters": {"allowed_domains": ["docs.parallel.ai"]}}]}
        if structured: args["text"] = {"format": {"type": "json_schema", "name": "search_facts", "schema": {
            "type": "object", "properties": {"modes": {"type": "array", "items": {"type": "string"}},
                "fast_usd_per_request": {"type": "number"}}, "required": ["modes", "fast_usd_per_request"], "additionalProperties": False}}}
        r = c.responses.create(**args); d = r.model_dump(mode="json")
        assert r.status == "completed" and r.output_text
        if structured:
            obj = json.loads(r.output_text)
            assert set(obj["modes"]) == {"turbo", "fast", "basic", "advanced"}
            assert obj["fast_usd_per_request"] == .001
        annotations = [a for x in d["output"] if x.get("type") == "message" for t in x.get("content", []) for a in t.get("annotations", [])]
        assert annotations
        return d, {"status": r.status, "citations": len(annotations), "response_id": r.id}

def raw(path, body):
    with httpx.Client(base_url="https://api.parallel.ai", headers={"x-api-key": KEY}, timeout=90, follow_redirects=False) as c:
        r = c.post(path, json=body); r.raise_for_status(); return r.json()

def entity():
    d = raw("/v1beta/findall/entity-search", {"entity_type": "companies", "objective": "Companies providing web search APIs for AI agents", "match_limit": 5})
    assert d["entities"] and all(x.get("url") for x in d["entities"])
    return d, {"entities": len(d["entities"])}

def images():
    d = raw("/v1/images/search", {"mode": "fast", "objective": "Research diagrams explaining retrieval augmented generation", "search_queries": ["retrieval augmented generation diagram"]})
    assert d["results"] and all(x.get("image_url") and x.get("source_page_url") for x in d["results"])
    return d, {"images": len(d["results"]), "downloaded": False}

if __name__ == "__main__":
    jobs = [("search-" + m, lambda m=m: search(m)) for m in ["turbo", "fast", "basic", "advanced"]]
    jobs += [("extract-full-pdf", lambda: extract(True)), ("extract-focused-errors", lambda: extract(False)),
        ("response-low", lambda: response("low")),
        ("response-medium-json", lambda: response("medium", True)), ("response-high", lambda: response("high")),
        ("entity-search", entity), ("image-search", images)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda job: check(*job), jobs))
    print("Passed", sum(r["passed"] for r in REPORT.values()), "/", len(REPORT), flush=True)
