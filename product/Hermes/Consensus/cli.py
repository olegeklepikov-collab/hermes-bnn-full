import argparse
import json
from pathlib import Path
from client import SERVICE_DIR, search

p = argparse.ArgumentParser(prog="consensus-bn", description="Поиск научных публикаций через Consensus.")
p.add_argument("command", choices=["search", "profiles", "record"])
p.add_argument("--query")
p.add_argument("--profile", default="discovery")
p.add_argument("--params", type=Path, help="JSON со всеми параметрами официального API")
p.add_argument("--output", type=Path)
p.add_argument("--refresh", action="store_true")
p.add_argument("--from-file", type=Path)
p.add_argument("--paper-id", help="DOI или точный URL записи в сохранённом результате")
a = p.parse_args()
profiles = json.loads((SERVICE_DIR / "config/profiles.json").read_text())
if a.command == "profiles": result = profiles
elif a.command == "record":
    if not a.from_file or not a.paper_id: p.error("Нужны --from-file и --paper-id.")
    rows = json.loads(a.from_file.read_text()).get("results", [])
    result = [x for x in rows if a.paper_id in [x.get("doi"), x.get("url")]]
    if not result: p.error("Точная запись отсутствует в файле; повторный поиск не выдаётся за чтение этой статьи.")
else:
    if a.profile not in profiles: p.error("Неизвестная конфигурация.")
    params = dict(profiles[a.profile]["params"])
    if a.params: params.update(json.loads(a.params.read_text()))
    if a.query: params["query"] = a.query
    try: result = search(params, a.refresh)
    except (ValueError, RuntimeError) as e: p.exit(2, str(e) + "\n")
text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
if a.output:
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(text); a.output.chmod(0o600)
    print(str(a.output))
else: print(text, end="")
