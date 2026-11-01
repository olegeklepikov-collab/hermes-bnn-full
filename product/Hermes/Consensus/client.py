"""Consensus REST search for the independent Hermes BN instance."""
import fcntl
import hashlib
import json
import math
import time
from pathlib import Path
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT / "Consensus"
FIELDS = set("query year_min year_max month_min month_max study_types human controlled sample_size_min sjr_min sjr_max citation_min duration_min duration_max exclude_preprints open_access publisher_name domain country journal_name clinical_guideline medical_mode include_semantic_score include_full_text_chunks page page_size".split())
DOMAINS = set("med bio cs chem psych phys mat eng env bus econ math poli agri edu soc geol geog hist art philo law ling".split())
STUDIES = {"bench experiment", "case report", "case study", "case-control study", "cohort study", "commentary or perspective", "cross-sectional study", "field study", "historical or archival analysis", "interview study", "literature review", "longitudinal / panel data study", "meta-analysis", "mixed methods study", "non-randomized experimental study", "non-rct in vitro", "other", "rct", "systematic review", "theoretical, modeling, or simulation study", "non-rct experimental", "non-rct observational study", "animal"}
ISO = set("ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw".split())

def validate(params):
    if set(params) - FIELDS: raise ValueError("Неизвестные параметры: " + ", ".join(sorted(set(params) - FIELDS)))
    if not str(params.get("query", "")).strip(): raise ValueError("Нужен исследовательский вопрос query.")
    for field in ["domain", "country"]:
        values = [x.strip().lower() for x in params.get(field, "").split(",") if x.strip()]
        allowed = DOMAINS if field == "domain" else ISO
        if set(values) - allowed: raise ValueError("Недопустимые значения " + field + ": " + ", ".join(sorted(set(values) - allowed)))
    if set(params.get("study_types") or []) - STUDIES: raise ValueError("Неподдерживаемый тип исследования.")
    for month, year in [("month_min", "year_min"), ("month_max", "year_max")]:
        if month in params and (not 1 <= params[month] <= 12 or year not in params): raise ValueError(month + " требует года и значения 1–12.")
    for low, high in [("year_min", "year_max"), ("duration_min", "duration_max"), ("sjr_min", "sjr_max")]:
        if low in params and high in params and params[low] > params[high]: raise ValueError(low + " больше " + high)
    for f in ["sjr_min", "sjr_max"]:
        if f in params and params[f] not in [1, 2, 3, 4]: raise ValueError(f + " должен быть от 1 до 4.")
    if not 1 <= params.get("page_size", 20) <= 1000 or not 0 <= params.get("page", 0) <= 49: raise ValueError("Неверный размер или номер страницы.")

def search(params, refresh=False):
    params = {k: v for k, v in params.items() if v is not None}; validate(params)
    cfg = json.loads((SERVICE_DIR / "config/access.json").read_text())
    values = dotenv_values(ROOT / "data/.env"); key = values.get(cfg["credential_env"])
    if not key: raise ValueError("Ключ Consensus пока не сохранён в защищённом поле Hermes BN.")
    size = min(params.get("page_size", 20), cfg["plan_max_page_size"])
    if (params.get("page", 0) + 1) * size > 1000: raise ValueError("Запрос выходит за пределы 1000 результатов одной темы.")
    cache = SERVICE_DIR / "cache"; cache.mkdir(exist_ok=True)
    cache_scope = hashlib.sha256(key.encode()).hexdigest() + json.dumps(params, sort_keys=True, ensure_ascii=False)
    file = cache / (hashlib.sha256(cache_scope.encode()).hexdigest() + ".json")
    if not refresh and file.exists() and time.time() - file.stat().st_mtime < cfg["cache_seconds"]:
        d = json.loads(file.read_text()); d["_hermes_bn"]["cache_hit"] = True; return d
    state = SERVICE_DIR / "state"; state.mkdir(exist_ok=True)
    with (state / "request.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stamp = state / "last-request.txt"
        if stamp.exists(): time.sleep(max(0, 1.1 - (time.time() - float(stamp.read_text()))))
        wire = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        stamp.write_text(str(time.time()))
        with httpx.Client(timeout=90, follow_redirects=False) as c:
            r = c.get("https://api.consensus.app/v1/search", headers={"x-api-key": key}, params=wire)
        if r.status_code == 429 and "retry-after" in r.headers:
            delay = min(30, max(1.1, float(r.headers["retry-after"]))); time.sleep(delay)
            stamp.write_text(str(time.time()))
            with httpx.Client(timeout=90, follow_redirects=False) as c:
                r = c.get("https://api.consensus.app/v1/search", headers={"x-api-key": key}, params=wire)
        if r.is_error: raise RuntimeError("Consensus HTTP " + str(r.status_code) + ": " + r.text[:1200])
        d = r.json()
    rows = d.get("results", []); identifiers = []
    for row in rows:
        identifiers.append(row.get("doi") or row.get("url") or row.get("title"))
    d["_hermes_bn"] = {"cache_hit": False, "requested_params": params,
        "applied_page_size": d.get("page_size"), "estimated_calls": max(1, math.ceil(len(rows) / 100)),
        "duplicate_identifiers": len(identifiers) - len(set(identifiers)),
        "papers_with_full_text_chunks": sum(bool(x.get("full_text_chunks")) for x in rows),
        "evidence_note": "Выдержки не равны полному тексту; отсутствие сведений не означает отсутствие результата исследования."}
    file.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n"); file.chmod(0o600)
    return d
