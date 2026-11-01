"""Enrich the completed five-candidate preview; export confirmed matches only."""
import json
import time
from pathlib import Path
from dotenv import dotenv_values
from parallel import Parallel

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "Parallel/проверки"
KEY = dotenv_values(ROOT / "data/.env")["PARALLEL_API_KEY"]
def save(n, d):
    p=OUT/(n+'.json');p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600)

run_id = json.loads((OUT / "findall-created.json").read_text())["findall_id"]
schema = {"type": "object", "properties": {
    "repository_focus": {"type": ["string", "null"], "description": "Main research disciplines described by the repository itself."},
    "publication_type": {"type": ["string", "null"], "description": "preprints, peer-reviewed papers and author manuscripts, or mixed. Do not treat preprints as peer-reviewed."},
    "source_url": {"type": ["string", "null"], "description": "Official repository about/help page supporting the classification."}},
    "required": ["repository_focus", "publication_type", "source_url"], "additionalProperties": False}
with Parallel(api_key=KEY,max_retries=0,timeout=120) as c:
    marker=OUT/'findall-enrichment-created.json'
    if not marker.exists():
        d=c.beta.findall.enrich(run_id,processor='base',output_schema={'type':'json','json_schema':schema}).model_dump(mode='json')
        save('findall-enrichment-created',d)
        print('Enrichment created',flush=True)
    for _ in range(30):
        d=c.beta.findall.result(run_id).model_dump(mode='json');save('findall-enriched-result',d)
        matched=[x for x in d.get('candidates',[]) if x.get('match_status')=='matched']
        if matched and all(x.get('output') and x['output'].get('repository_focus') for x in matched):break
        time.sleep(15)
    else:raise RuntimeError('Enrichment still pending; retain existing job')
    save('findall-confirmed-enriched',matched)
    save('findall-enrichment-report',{'passed':True,'id':run_id,'returned':len(d['candidates']),'confirmed':len(matched),
        'excluded_unverified':len(d['candidates'])-len(matched),'all_have_source_url':all(x['output'].get('source_url') for x in matched)})
    print('Enriched confirmed records',len(matched),flush=True)
