"""Small serial checks of authenticated search and available plan features."""
import json
from pathlib import Path
from client import search, validate

OUT = Path(__file__).resolve().parent / "проверки"
REPORT = {}
def save(n, d):
    f=OUT/(n+'.json');f.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');f.chmod(0o600)

def check(name, params, conditions):
    try:
        d=search(params,refresh=True);save(name,d);rows=d['results']
        assert rows, 'No records for this bounded query'
        assertions=[]
        for label, predicate in conditions:
            verified=[x for x in rows if predicate(x) is not None]
            assert all(predicate(x) for x in verified), label
            assertions.append({'condition':label,'records_with_metadata':len(verified)})
        REPORT[name]={'passed':True,'records':len(rows),'applied_page_size':d.get('page_size'),
                      'assertions':assertions,'full_text_records':sum(bool(x.get('full_text_chunks')) for x in rows)}
    except Exception as e:REPORT[name]={'passed':False,'error':type(e).__name__+': '+str(e)[:1000]}
    save('api-report',REPORT);print(name,REPORT[name],flush=True)

base={'page':0,'page_size':5,'include_semantic_score':True}
check('api-recent-technical',{**base,'query':'retrieval augmented generation hallucinations','domain':'cs',
    'year_min':2024,'year_max':2026,'month_min':1,'month_max':10,'exclude_preprints':True},[
    ('year range',lambda x:2024<=x['publish_year']<=2026 if x.get('publish_year') else None),
    ('no preprints',lambda x:not x['is_preprint'] if x.get('is_preprint') is not None else None)])
check('api-open-review-excerpts',{**base,'query':'feedback effects student learning','domain':'edu,psych',
    'study_types':['meta-analysis','systematic review'],'open_access':True,'include_full_text_chunks':True},[
    ('review design',lambda x:x['study_type'] in ['meta-analysis','systematic review'] if x.get('study_type') else None)])
check('api-human-controlled',{**base,'query':'exercise sleep quality','human':True,'controlled':True,
    'study_types':['rct'],'sample_size_min':50,'duration_min':7,'duration_max':365,'country':'us,gb'},[
    ('RCT',lambda x:x['study_type']=='rct' if x.get('study_type') else None),
    ('sample minimum',lambda x:x['sample_size']>=50 if x.get('sample_size') is not None else None),
    ('duration',lambda x:7<=x['study_duration_days']<=365 if x.get('study_duration_days') is not None else None)])
check('api-journal-citations',{**base,'query':'employee training organizational performance','sjr_min':1,'sjr_max':2,'citation_min':20,'exclude_preprints':True},[
    ('journal quartile',lambda x:1<=x['sjr_best_quartile']<=2 if x.get('sjr_best_quartile') else None),
    ('citation threshold',lambda x:x['citation_count']>=20 if x.get('citation_count') is not None else None)])
check('api-pagination',{'query':'employee training organizational performance','domain':'bus,econ,soc,psych',
    'exclude_preprints':True,'include_semantic_score':True,'page':1,'page_size':20},[])
check('api-preferred-journal',{**base,'query':'employee training organizational performance','journal_name':'Human Resource Management Journal'},[])
check('api-broad-excerpts',{**base,'query':'retrieval augmented generation hallucinations','domain':'cs',
    'include_full_text_chunks':True},[])
try:validate({'query':'test','country':'zz'});raise AssertionError('Unknown country accepted')
except ValueError:REPORT['client-country-guard']={'passed':True,'note':'Rejected before remote call; no quota used.'}
first=json.loads((OUT/'api-business.json').read_text())
cached=search(first['_hermes_bn']['requested_params']);assert cached['_hermes_bn']['cache_hit']
REPORT['client-cache']={'passed':True,'note':'Existing result reused without an API request.'}
save('api-report',REPORT)
print('Final',REPORT,flush=True)
