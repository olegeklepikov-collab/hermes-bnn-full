"""Small SDK/API jobs, with persistent identifiers for safe continuation."""
import concurrent.futures
import json
import threading
import time
from pathlib import Path
from dotenv import dotenv_values
from parallel import Parallel
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]
REPORT = json.loads((OUT / "jobs-report.json").read_text()) if (OUT / "jobs-report.json").exists() else {}
LOCK = threading.Lock()

def save(name, value):
    p = OUT / (name + ".json"); p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n"); p.chmod(0o600)

def record(name, value):
    with LOCK:
        REPORT[name] = value; save("jobs-report", REPORT)
        print(name, value, flush=True)

def task():
    schema = {"type": "object", "properties": {
        "search_fast_usd_per_1000": {"type": "number"},
        "extract_usd_per_1000_urls": {"type": "number"}, "source_url": {"type": "string"}},
        "required": ["search_fast_usd_per_1000", "extract_usd_per_1000_urls", "source_url"], "additionalProperties": False}
    with Parallel(api_key=KEY, max_retries=0, timeout=150) as c:
        run = c.task_run.create(input="Read https://docs.parallel.ai/getting-started/pricing and return the published prices per 1000 for Search fast and Extract. Use the official pricing page as the source.",
            processor="base", memory_scope_key="hermes-bn", enable_events=True,
            source_policy={"include_domains": ["docs.parallel.ai"]},
            task_spec={"output_schema": {"type": "json", "json_schema": schema}})
        d = run.model_dump(mode="json"); save("sdk-task-created", d)
        record("task_created", {"id": run.run_id})
        events = []
        with c.task_run.events(run.run_id, timeout=150) as stream:
            for event in stream:
                e = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
                events.append(e)
                if "completed" in json.dumps(e).lower() or len(events) >= 200: break
        save("sdk-task-events", events)
        result = c.task_run.result(run.run_id, api_timeout=90, timeout=120)
        d = result.model_dump(mode="json"); save("sdk-task-result", d)
        obj = d["output"]["content"]
        if isinstance(obj, str): obj = json.loads(obj)
        assert obj["search_fast_usd_per_1000"] == 1 and obj["extract_usd_per_1000_urls"] == 1
        assert "docs.parallel.ai" in obj["source_url"] and d["output"].get("basis")
        record("task_sdk", {"passed": True, "id": run.run_id, "events": len(events), "basis": True})

def findall():
    with Parallel(api_key=KEY, max_retries=0, timeout=120) as c:
        existing = OUT / "findall-created.json"
        run = c.beta.findall.retrieve(json.loads(existing.read_text())["findall_id"]) if existing.exists() else c.beta.findall.create(objective="Find public scholarly repositories with freely accessible full research papers, such as arXiv, PubMed Central or Zenodo.",
            entity_type="scholarly repositories", generator="preview", match_limit=5, memory_scope_key="hermes-bn",
            match_conditions=[{"name": "research_repository", "description": "The entity is a repository hosting full academic research papers."},
                {"name": "free_full_text", "description": "Full research papers can be read without a paid subscription."}])
        save("findall-created", run.model_dump(mode="json")); record("findall_created", {"id": run.findall_id})
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            r = c.beta.findall.retrieve(run.findall_id); save("findall-status", r.model_dump(mode="json"))
            if r.status.status in ["completed", "failed", "cancelled"]: break
            time.sleep(20)
        assert r.status.status == "completed", str(r.status)
        d = c.beta.findall.result(run.findall_id).model_dump(mode="json"); save("findall-result", d)
        assert d.get("candidates")
        record("findall", {"passed": True, "id": run.findall_id, "candidates": len(d["candidates"]), "generator": "preview"})

def responses():
    previous = json.loads((OUT / "response-low.json").read_text())["id"]
    with OpenAI(api_key=KEY, base_url="https://api.parallel.ai/v1", max_retries=0, timeout=150) as c:
        r = c.responses.create(model="parallel", input="Сколько режимов Search перечислено в предыдущем ответе? Верните только цифру.",
            previous_response_id=previous, reasoning={"effort": "low"})
        save("response-continuation", r.model_dump(mode="json"))
        assert r.status == "completed" and r.output_text.strip() == "4"
        events = []; final = None
        with c.responses.create(model="parallel", input="По официальной документации Parallel назовите рекомендованный для агентов режим Search. Ответьте одним предложением по-русски со ссылкой.",
            reasoning={"effort": "low"}, tools=[{"type": "web_search", "filters": {"allowed_domains": ["docs.parallel.ai"]}}], stream=True) as stream:
            for event in stream:
                events.append(event.model_dump(mode="json"))
                if event.type == "response.completed": final = event.response; break
        save("response-stream-events", events)
        assert final is not None and final.status == "completed" and "fast" in final.output_text.lower()
        record("responses_continuation_stream", {"passed": True, "events": len(events), "previous_id": previous, "stream_id": final.id})

def run(name, fn):
    try: fn()
    except Exception as e: record(name + "_error", {"error": type(e).__name__ + ": " + str(e)[:1400]})

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [("task", task), ("findall", findall), ("responses", responses)]
        labels = {"task": "task_sdk", "findall": "findall", "responses": "responses_continuation_stream"}
        list(pool.map(lambda job: run(*job), [j for j in jobs if not REPORT.get(labels[j[0]], {}).get("passed")]))
