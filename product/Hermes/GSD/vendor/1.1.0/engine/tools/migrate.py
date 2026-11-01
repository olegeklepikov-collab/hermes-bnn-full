"""Явный импорт v2 → v3. Импорт не наследует проверенность или полномочия.
Положительные привязки разрешены только для поставляемых искусственных проверок.
"""
from copy import deepcopy
from datetime import datetime, timezone
from records import GROUPS, review_binding, validate_case, digest, dependency_fingerprint

def migrate_v2(old,*,budget,synthetic_revalidation=False):
    c=deepcopy(old)
    if c.get('version')!='2.0':raise ValueError('Ожидается v2')
    if synthetic_revalidation and c['data_kind']!='synthetic':raise ValueError('Нельзя автоматически подтвердить реальный импорт')
    c['version']='3.0';c['contract']['budget']=deepcopy(budget)
    for group in ('action_proposals','action_reviews','procedure_runs'):c[group]=[]
    for group in GROUPS:
        for x in c.get(group,[]):
            if group not in ('sources','contexts','claims'):x.setdefault('version',1)
    for group in ('tests','models','authorities','decisions'):
        for x in c[group]:x['use_state']='active' if synthetic_revalidation else 'requires_review'
    for r in c['reviews']:r.update(binding=None,lifecycle='stale',supersedes_ids=[])
    for a in c['authorities']:
        a.update(valid_from='1970-01-01T00:00:00Z',proposal_digest=None)
        a['verification']='unverified'
    for d in c['decisions']:
        d['imported_original_status']=d['status'];d['proposal_id']=None
        if d['status']=='authorized':d['status']='recommendation'
        elif d['status']=='sent':d['status']='outcome_unknown'  # Возможный внешний эффект не превращается в неотправленную рекомендацию.
    for m in c['models']:
        m.update(method_contract=None,assertion_claim_id=None,assessment_review_id=None)
        if m['identification_status']=='identified_within_scope':m['identification_status']='candidate'
    for a in c['artifacts']:a.update(input_fingerprint=None,semantic_result_refs=[],accepted_limitations_by=[])
    for a in c['source_applications']:
        a.update(run_id=None,target_versions={})
        if a['status']=='applied':a['status']='read';a['reason']='Импорт сохраняет текст, но не наследует исполнение по новому договору'
    if not synthetic_revalidation:
        for x in c['claims']:
            if x['M']['epistemic_status'] in ('supported','refuted'):
                x['M']['epistemic_status']='unassessed';x['M']['allowed_use']='discovery'
                x['T']['verification']['status']='stale'
                for dim in ('V','A','R'):x['J'][dim]['state']='unknown';x['J'][dim]['limitations'].append('Импорт: требуется проверка v3')
            if x['M']['probability']:x['M']['probability']=None;x['M']['modality']='possible'
        c['status']='new'
    else:
        for r in c['reviews']:
            r['binding']=review_binding(c,r['target_claim_id'],r['evidence_ids']);r['lifecycle']='active'
    return c

if __name__=='__main__':
    import argparse,json
    from pathlib import Path
    from records import load_json
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('output',type=Path);p.add_argument('--budget',type=Path,required=True)
    a=p.parse_args();c=migrate_v2(load_json(a.input),budget=load_json(a.budget));issues=validate_case(c)
    if issues:raise SystemExit('Импорт требует ремонта: '+','.join(i.code for i in issues))
    a.output.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
