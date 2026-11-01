"""Temporary public-source Monitor checks; always cancel only created test IDs."""
import concurrent.futures
import json
import time
from pathlib import Path
from dotenv import dotenv_values
from parallel import Parallel

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]

def save(name, value):
    p = OUT / (name + ".json"); p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n"); p.chmod(0o600)

def one(kind):
    report = {}; monitor_id = None
    with Parallel(api_key=KEY, max_retries=0, timeout=120) as c:
        try:
            args = json.loads((ROOT / "Parallel/config" / ("monitor-test-" + kind + ".json")).read_text())
            result = c.monitor.create(**args); d = result.model_dump(mode="json")
            save("monitor-" + kind + "-created", d); monitor_id = result.monitor_id
            report["id"] = monitor_id; print(kind, "created", monitor_id, flush=True)
            read = c.monitor.retrieve(monitor_id); save("monitor-" + kind + "-read", read.model_dump(mode="json"))
            changed = c.monitor.update(monitor_id, frequency="1d"); save("monitor-" + kind + "-updated", changed.model_dump(mode="json"))
            assert changed.frequency == "1d"
            c.monitor.trigger(monitor_id); report["trigger_accepted"] = True
            deadline = time.monotonic() + 240
            events = None
            while time.monotonic() < deadline:
                events = c.monitor.events(monitor_id, include_completions=True, limit=10).model_dump(mode="json")
                save("monitor-" + kind + "-events", events)
                if events.get("events"): break
                time.sleep(15)
            report["events"] = len((events or {}).get("events", []))
            report["passed"] = report["events"] > 0
            if not report["passed"]: report["limitation"] = "Trigger accepted; no completion event within bounded check."
        except Exception as e:
            report["error"] = type(e).__name__ + ": " + str(e)[:1000]
        finally:
            if monitor_id:
                try:
                    cancelled = c.monitor.cancel(monitor_id); save("monitor-" + kind + "-cancelled", cancelled.model_dump(mode="json"))
                    final = c.monitor.retrieve(monitor_id); save("monitor-" + kind + "-final", final.model_dump(mode="json"))
                    report["final_status"] = final.status
                    assert final.status == "cancelled"
                except Exception as e: report["cleanup_error"] = type(e).__name__ + ": " + str(e)[:1000]
            save("monitor-" + kind + "-report", report)
    print(kind, report, flush=True)
    return report

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows = dict(zip(["event_stream", "snapshot"], pool.map(one, ["event_stream", "snapshot"])))
    save("monitor-report", rows)
