"""Типизированные зависимости, актуальность оснований и локальный договор допуска.

Эта программа проверяет объявленные структурные/логические ограничения. Подлинность
источников, достаточность предметного метода и полномочие проверяются внешней средой.
Ни одна функция модуля не выполняет внешнее действие.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Iterable
from _base import (Issue, ROOT, PROFILES, RISK_KEYS, canonical, digest, load_json,
                   choose_profile, time_value, has_cycle, base_validate_case)

GROUPS=('contexts','sources','evidence','claims','relations','models','genesis','tests',
        'authorities','reviews','artifacts','source_applications','decisions',
        'action_proposals','action_reviews','procedure_runs')
# Every declared semantic link is described once. Dependency cycles are permitted;
# circular PROOF remains separately prohibited by the base validator.
REFS={
 'contexts':('standard_source_ids',),
 'sources':('derived_from',),
 'evidence':('source_id','context_id','transformation.input_evidence_ids'),
 'claims':('C.context_id','C.transport_from_claim_id','C.transport_review_id',
           'J.premise_ids','J.alternative_claim_ids','J.defeater_ids','J.unresolved_defeater_ids',
           'J.evidence_ids','J.V.basis_evidence_ids','J.A.basis_evidence_ids','J.R.basis_evidence_ids',
           'S.source_ids','T.verification.result_evidence_ids','M.probability.model_id','M.probability.basis_evidence_ids'),
 'relations':('from_id','to_id','claim_id','context_id'),
 'models':('claim_ids','relation_ids','context_id','assertion_claim_id','assessment_review_id','method_contract.parameter_evidence_ids'),
 'genesis':('context_id','claim_ids','event_evidence_ids'),
 'tests':('question_claim_id','applicability_claim_id','cost_risk_claim_id','competitor_claim_ids','authority_id','result_evidence_ids'),
 'authorities':('context_id','policy_source_ids','verification_evidence_ids'),
 'reviews':('target_claim_id','evidence_ids','supersedes_ids','waiver.authority_id','waiver.policy_evidence_ids','waiver.compensating_claim_ids'),
 'artifacts':('context_id','claim_ids','evidence_ids','semantic_result_refs'),
 'source_applications':('target_claim_ids','input_refs','result_artifact_ids','run_id'),
 'decisions':('context_id','basis_claim_ids','authority_id','execution_evidence_ids','proposal_id'),
 'action_proposals':('context_id',),
 'action_reviews':('decision_id','proposal_id','context_id','evidence_ids','supersedes_ids'),
 'procedure_runs':('target_claim_ids','input_refs','output_ids'),
}
def dotted(x:Mapping[str,Any],path:str)->Any:
    value:Any=x
    for p in path.split('.'):
        if not isinstance(value,Mapping):return None
        value=value.get(p)
    return value

def indexes(case:Mapping[str,Any])->tuple[dict[str,Any],dict[str,str]]:
    nodes={};groups={}
    for group in GROUPS:
        for x in case.get(group,[]):nodes[x['id']]=x;groups[x['id']]=group
    return nodes,groups

def object_refs(x:Mapping[str,Any],group:str)->set[str]:
    refs:set[str]=set()
    for field in REFS.get(group,()):
        value=dotted(x,field)
        if isinstance(value,str):refs.add(value)
        elif isinstance(value,list):refs.update(v for v in value if isinstance(v,str))
    return refs

def dependency_impact(case:Mapping[str,Any],changed_ids:Iterable[str])->dict[str,list[str]]:
    nodes,groups=indexes(case);changed=set(changed_ids)
    if not changed<=set(nodes):raise ValueError('Изменённый объект отсутствует')
    reverse={x:set() for x in nodes}
    for key,x in nodes.items():
        for ref in object_refs(x,groups[key]):
            if ref in reverse:reverse[ref].add(key)
    # Review supplies permission to USE a claim; this is not a circular logical proof.
    for r in case.get('reviews',[]):
        if r['target_claim_id'] in reverse:reverse[r['id']].add(r['target_claim_id'])
    todo=list(changed);seen=set(changed)
    while todo:
        for child in reverse[todo.pop()]:
            if child not in seen:seen.add(child);todo.append(child)
    return {group:sorted(k for k in seen if groups[k]==group) for group in GROUPS}

def invalidate_dependents(case,changed_claim_ids):return set(dependency_impact(case,changed_claim_ids)['claims'])

EXCLUDED_BINDING_GROUPS=frozenset(('reviews','action_reviews','procedure_runs','source_applications','artifacts'))
def dependency_snapshot(case:Mapping[str,Any],roots:Iterable[str])->dict[str,dict[str,Any]]:
    """Материальная цепочка чтения; проверки исключены во избежание самохеширования.
    Review хранится как результат контроля, а не как собственное свидетельство.
    """
    nodes,groups=indexes(case);seen=set();todo=list(roots);result={}
    while todo:
        key=todo.pop()
        if key in seen:continue
        seen.add(key)
        if key not in nodes:raise ValueError('Неразрешённая зависимость '+str(key))
        if groups[key] in EXCLUDED_BINDING_GROUPS:continue
        value=nodes[key]
        result[key]={'type':groups[key],'version':value.get('version'),'digest':digest(value)}
        todo.extend(object_refs(value,groups[key]))
    return dict(sorted(result.items()))

def dependency_fingerprint(case,roots):return digest(dependency_snapshot(case,roots))

def review_binding(case:Mapping[str,Any],claim_id:str,evidence_ids:Iterable[str]=())->dict[str,Any]:
    nodes,_=indexes(case);c=nodes[claim_id];ctx=nodes[c['C']['context_id']]
    return {'target_version':c['version'],'target_digest':digest(c),
            'context_version':ctx['version'],'context_digest':digest(ctx),
            'dependency_fingerprint':dependency_fingerprint(case,[claim_id,*evidence_ids])}

def review_current(case,r)->bool:
    if r.get('lifecycle')!='active' or not r.get('binding'):return False
    try:return r['binding']==review_binding(case,r['target_claim_id'],r['evidence_ids'])
    except (KeyError,TypeError,ValueError):return False

def usable_evidence(case,eid)->bool:
    nodes,groups=indexes(case);visiting=set();memo={}
    def good_source(sid):
        key=('s',sid)
        if key in memo:return memo[key]
        if key in visiting:return False
        s=nodes.get(sid)
        if not s or groups[sid]!='sources':return False
        visiting.add(key)
        ok=(s['availability']=='available' and s['verification_status']=='checked' and s['kind']!='model'
            and (case['data_kind']=='synthetic' or s['kind']!='synthetic') and all(good_source(p) for p in s['derived_from']))
        visiting.remove(key);memo[key]=ok;return ok
    def good_evidence(key):
        token=('e',key)
        if token in memo:return memo[token]
        if token in visiting:return False
        e=nodes.get(key)
        if not e or groups[key]!='evidence':return False
        visiting.add(token)
        t=e['transformation'];parents=t['input_evidence_ids'] if t else []
        ok=(e['observation_state']=='observed' and e['mode']!='model' and
            (case['data_kind']=='synthetic' or e['mode']!='synthetic') and good_source(e['source_id']) and all(good_evidence(p) for p in parents))
        visiting.remove(token);memo[token]=ok;return ok
    return good_evidence(eid)

def usable_source(case,source_id)->bool:
    nodes,groups=indexes(case);seen=set();todo=[source_id]
    while todo:
        sid=todo.pop()
        if sid in seen:continue
        seen.add(sid);src=nodes.get(sid)
        if not src or groups.get(sid)!='sources' or src['availability']!='available' or src['verification_status']!='checked' or src['kind']=='model' or (case['data_kind']!='synthetic' and src['kind']=='synthetic'):return False
        todo.extend(src['derived_from'])
    return True

def authority_valid(case,authority_id,now=None)->bool:
    now=now or datetime.now(timezone.utc);nodes,_=indexes(case);a=nodes.get(authority_id)
    if not a:return False
    try:
        ctx=nodes[a['context_id']]
        return (a['verification']=='externally_verified' and a.get('use_state','active')=='active'
                and time_value(a['valid_from'])<=now<time_value(a['valid_until'])
                and (not ctx['expires_at'] or now<time_value(ctx['expires_at']))
                and bool(a['verification_evidence_ids']) and all(usable_evidence(case,e) for e in a['verification_evidence_ids'])
                and bool(a['policy_source_ids']) and all(usable_source(case,p) for p in a['policy_source_ids']))
    except (KeyError,ValueError,TypeError):return False

def validate_case(case:Any,*,now:datetime|None=None)->list[Issue]:
    now=now or datetime.now(timezone.utc)
    base=base_validate_case(case,now=now)
    if any(i.code in ('SCHEMA','DUPLICATE_ID','MISSING_REF') for i in base):return base
    out=list(base)
    def err(code,path,detail):out.append(Issue(code,str(path),detail))
    nodes,groups=indexes(case)
    total=sum(len(case.get(g,[])) for g in GROUPS)
    if len(nodes)!=total:err('DUPLICATE_ID','case','Идентичность повторяется между коллекциями');return out
    for key,x in nodes.items():
        for ref in object_refs(x,groups[key]):
            if ref not in nodes:err('MISSING_REF',key,'Отсутствует '+ref)
    if any(i.code=='MISSING_REF' for i in out):return out
    budget=case['contract']['budget']
    if budget['reserve_steps']>=budget['step_limit']:err('BUDGET_RESERVE','contract','Резерв завершения не оставляет исполнительного бюджета')
    for c in case['claims']:
        key=c['id'];j=c['J'];v=c['T']['verification'];m=c['M'];ctx=nodes[c['C']['context_id']]
        for dim in ('V','A','R'):
            if j[dim]['state']=='pass' and not all(usable_evidence(case,e) for e in j[dim]['basis_evidence_ids']):err('J_CHAIN_UNUSABLE',key+'/'+dim,'Необходимая цепочка источника или преобразования непригодна')
        if v['status']=='completed' and not all(usable_evidence(case,e) for e in v['result_evidence_ids']):err('T_UNUSABLE',key,'Фактический результат T не может быть неизмеренным или зависеть от отозванного основания')
        if m['epistemic_status'] in ('supported','refuted'):
            dims=set(ctx['required_dimensions'])|{d for d in ('V','A','R') if j[d]['required_for_use']}
            if not dims:err('EMPTY_STANDARD',key,'Сильный статус требует хотя бы одного явно обязательного класса основания')
            if any(j[d]['state']!='pass' for d in dims):err('STRONG_J',key,'Обязательные V/A/R не пройдены')
            if not v['result_evidence_ids'] or not all(usable_evidence(case,e) for e in v['result_evidence_ids']):err('STRONG_T',key,'Нет пригодного результата для поддержки или опровержения')
            if ctx['expires_at'] and time_value(ctx['expires_at'])<=now:err('EXPIRED_CONTEXT',key,'Истёк контекст применения')
            reviews=[r for r in case['reviews'] if r['target_claim_id']==key and review_current(case,r)]
            required={'G01'}|set({'causal':'G02','forecast':'G04','normative':'G08','recommendation':'G05'}.get(c['P']['kind'],'').split())
            passed={r['gate'] for r in reviews if r['verdict']=='pass' and r['execution_state']=='completed'}
            if not required<=passed:err('STRONG_REVIEW',key,'Нет актуальной проверки '+','.join(sorted(required-passed)))
        p=m['probability']
        if p:
            model=nodes[p['model_id']]
            if not model.get('method_contract') or not model['claim_ids'] or not all(usable_evidence(case,e) for e in p['basis_evidence_ids']):err('PROBABILITY_WARRANT',key,'Число требует предметного договора модели, переменных и пригодных параметров')
    for t in case['tests']:
        if t.get('use_state','active')!='active':continue
        if t['status'] in ('planned','requested','running','cancelled') and t['result_evidence_ids']:err('TEST_UNRUN_RESULT',t['id'],'План/незавершённый тест не содержит неоформленный конечный результат')
        if t['status']=='completed' and (not t['result_evidence_ids'] or not all(usable_evidence(case,e) for e in t['result_evidence_ids'])):err('TEST_UNUSABLE',t['id'],'Завершённый тест не имеет пригодного результата')
    for r in case['reviews']:
        if r['lifecycle']=='superseded':
            replacements=[n for n in case['reviews'] if r['id'] in n['supersedes_ids'] and n['lifecycle']=='active' and n['gate']==r['gate'] and n['target_claim_id']==r['target_claim_id'] and n['execution_state']=='completed' and review_current(case,n)]
            if not replacements:err('ORPHAN_SUPERSESSION',r['id'],'Прежняя проверка не замещена актуальной адресной проверкой')
        if r['lifecycle']!='active':continue
        if r['execution_state']=='completed' and not review_current(case,r):err('REVIEW_STALE_BINDING',r['id'],'Проверка не связана с текущим P/S/C и существенными зависимостями')
        if r['verdict']=='pass' and not all(usable_evidence(case,e) for e in r['evidence_ids']):err('REVIEW_CHAIN_UNUSABLE',r['id'],'Предок свидетельства непригоден')
        for oldid in r['supersedes_ids']:
            old=nodes[oldid]
            if groups[oldid]!='reviews' or old['target_claim_id']!=r['target_claim_id'] or old['gate']!=r['gate'] or old['lifecycle']!='superseded':err('REVIEW_SUPERSESSION',r['id'],'Замещение требует того же объекта/проверки и явно архивированного предшественника')
        if r['verdict']=='waived':
            w=r['waiver']
            if not w:continue
            if not authority_valid(case,w['authority_id'],now):err('WAIVER_AUTHORITY',r['id'],'Нет текущего проверенного основания исключения')
            if not w['policy_evidence_ids'] or not all(usable_evidence(case,e) for e in w['policy_evidence_ids']):err('WAIVER_POLICY',r['id'],'Отсутствует пригодное разрешение исключения')
            if not w['compensating_claim_ids'] or any(nodes[c]['M']['epistemic_status']!='supported' for c in w['compensating_claim_ids']):err('WAIVER_COMPENSATION',r['id'],'Компенсирующая мера не подтверждена')
            if any(x['target_claim_id']==r['target_claim_id'] and x['gate']==r['gate'] and x['verdict']=='kill_fail' and x['lifecycle']!='superseded' for x in case['reviews']):err('WAIVER_KILL',r['id'],'Непогашенный kill_fail не исключается')
    for mod in case['models']:
        if mod.get('use_state','active')!='active':continue
        if mod['identification_status']=='identified_within_scope':
            a=nodes.get(mod['assertion_claim_id']);rv=nodes.get(mod['assessment_review_id'])
            if not mod['claim_ids'] or not mod['method_contract'] or not a or not rv:err('MODEL_UNGROUNDED',mod['id'],'Идентификация требует переменных, метода, отдельного утверждения и проверки');continue
            if a['M']['epistemic_status']!='supported' or rv['target_claim_id']!=a['id'] or rv['verdict']!='pass' or not review_current(case,rv):err('MODEL_STRONG_STATUS',mod['id'],'Сильная метка модели не подтверждена актуальным основанием')
    for ap in case['source_applications']:
        if ap['status']!='applied':continue
        run=nodes.get(ap['run_id']);targets=ap['target_claim_ids']
        if not run or groups.get(ap['run_id'])!='procedure_runs':err('APPLICATION_NO_RUN',ap['id'],'Нет зарегистрированного исполнения');continue
        if run['procedure_id']!=ap['procedure_id'] or set(run['target_claim_ids'])!=set(targets) or run['status'] not in ('pass','limited'):err('APPLICATION_TARGET',ap['id'],'Исполнение относится к иной процедуре или цели')
        if set(ap['result_artifact_ids'])!=set(run['output_ids']):err('APPLICATION_OUTPUT',ap['id'],'Результат не принадлежит указанному исполнению')
        for c in targets:
            if ap['target_versions'].get(c)!=nodes[c]['version']:err('APPLICATION_VERSION',ap['id'],'Применение старой версии тезиса')
            if not any(c in nodes[a]['claim_ids'] for a in ap['result_artifact_ids']):err('APPLICATION_FOREIGN_OUTPUT',ap['id'],'Выход другого тезиса не закрывает применение')
        if run['dependency_fingerprint']!=dependency_fingerprint(case,run['input_refs']):err('APPLICATION_STALE',ap['id'],'Изменилось основание исполненной операции')
    for d in case['decisions']:
        pid=d['proposal_id']
        if d['status'] in ('authorized','sent','executed') and not pid and not (d.get('use_state')=='requires_review' and d.get('imported_original_status')=='executed' and d['status']=='executed'):err('ACTION_NO_EXACT_PROPOSAL',d['id'],'Требуется точная операция с параметрами')
        if pid and groups.get(pid)!='action_proposals':err('ACTION_WRONG_TARGET',d['id'],'Неверный тип предложения')
        if pid and (nodes[pid]['context_id']!=d['context_id'] or nodes[pid]['operation_id']!=d['selected_operation_id']):err('ACTION_SCOPE',d['id'],'Изменена операция или контекст')
    for r in case['action_reviews']:
        if r['lifecycle']=='superseded':
            replacements=[n for n in case['action_reviews'] if r['id'] in n['supersedes_ids'] and n['lifecycle']=='active' and n['gate']==r['gate'] and n['decision_id']==r['decision_id']]
            if not replacements:err('ORPHAN_ACTION_SUPERSESSION',r['id'],'Запрет действия не замещён актуальной адресной проверкой')
        if r['lifecycle']!='active':continue
        p=nodes[r['proposal_id']];d=nodes[r['decision_id']]
        if groups[r['proposal_id']]!='action_proposals' or groups[r['decision_id']]!='decisions':err('ACTION_REVIEW_TYPE',r['id'],'Неверные типы целей');continue
        if r['proposal_digest']!=digest(p) or r['proposal_id']!=d['proposal_id'] or r['context_id']!=d['context_id']:err('ACTION_REVIEW_BINDING',r['id'],'Подменены точные параметры/версия действия')
        fp=dependency_fingerprint(case,[r['decision_id'],r['proposal_id'],*r['evidence_ids']])
        if r['dependency_fingerprint']!=fp:err('ACTION_REVIEW_STALE',r['id'],'Изменились основания решения')
        if r['verdict']=='pass' and not all(usable_evidence(case,e) for e in r['evidence_ids']):err('ACTION_REVIEW_UNUSABLE',r['id'],'Нет пригодного свидетельства проверки действия')
        if r['allow_provisional_basis'] and not r['provisional_rationale']:err('PROVISIONAL_ACTION_NO_RATIONALE',r['id'],'Действие при гипотезе требует отдельного обоснования')
    return out


def action_boundary(case:Mapping[str,Any],decision_id:str,*,trusted_authority_bindings:Mapping[str,str]|None=None,
                    trusted_authority_ids:frozenset[str]=frozenset(),now:datetime|None=None)->dict[str,Any]:
    """Внешнее доверие связывается с отпечатком Authority, не с одним строковым ID.
    Набор передаётся доверенной средой, не извлекается из анализируемого документа.
    """
    now=now or datetime.now(timezone.utc); reasons=[i.code for i in validate_case(case,now=now)]
    nodes,groups=indexes(case);d=nodes.get(decision_id)
    if not d or groups.get(decision_id)!='decisions':reasons.append('DECISION_NOT_FOUND')
    else:
        a=nodes.get(d['authority_id']);proposal=nodes.get(d.get('proposal_id'))
        if case['status'] in ('blocked','partial','degraded','awaiting_authority','closed'):reasons.append('RUN_NOT_EXECUTABLE')
        if case['data_kind']=='synthetic':reasons.append('SYNTHETIC_NOT_EXECUTABLE')
        if case['contract']['intended_use']!='authorized_execution':reasons.append('ANALYSIS_NOT_EXECUTION')
        if d['status']!='authorized':reasons.append('NOT_AUTHORIZED_STATE')
        if d.get('use_state')!='active':reasons.append('DECISION_REQUIRES_REVIEW')
        if choose_profile(case['requested_profile'],case['risk'])['risk_incomplete']:reasons.append('RISK_UNKNOWN')
        if not a or not authority_valid(case,a['id'],now):reasons.append('AUTHORITY_INVALID')
        if a and (trusted_authority_bindings or {}).get(a['id'])!=digest(a):reasons.append('NO_BOUND_EXTERNAL_ATTESTATION')
        if not proposal:reasons.append('NO_EXACT_ACTION')
        else:
            if time_value(proposal['expires_at'])<=now:reasons.append('PROPOSAL_EXPIRED')
            if not a or a['proposal_digest']!=digest(proposal) or a['operation_id']!=proposal['operation_id'] or a['context_id']!=proposal['context_id']:reasons.append('AUTHORITY_ACTION_MISMATCH')
        basis=d['basis_claim_ids'];scope_reviews=[r for r in case['action_reviews'] if r['decision_id']==decision_id and r['lifecycle']=='active']
        # A stale denial remains unresolved, never disappears as a side effect of mutation.
        denials=[r for r in case['reviews'] if r['target_claim_id'] in basis and r['verdict'] in ('kill_fail','hard_fail') and r['lifecycle']!='superseded' and r['gate'] in ('G05','G07','G08','SAFETY')]
        denials += [r for r in case['action_reviews'] if r['decision_id']==decision_id and r['verdict'] in ('kill_fail','hard_fail') and r['lifecycle']!='superseded']
        if denials:reasons.append('UNRESOLVED_DENIAL')
        if any(nodes[c]['M']['allowed_use'] in ('none','discovery','comparison') for c in basis):reasons.append('BASIS_USE_FORBIDDEN')
        passed={r['gate'] for r in scope_reviews if r['verdict']=='pass' and time_value(r['expires_at'])>now}
        required={'G05','G08'}
        rank=PROFILES.index(choose_profile(case['requested_profile'],case['risk'])['selected'])
        if rank>=4:required|={'SAFETY','INDEPENDENCE'}
        if rank>=5:required|={'G07'}
        if not required<=passed:reasons.append('ACTION_SCOPED_REVIEWS_MISSING')
        if any(nodes[c]['M']['epistemic_status']!='supported' for c in basis) and not any(r['gate']=='G05' and r['verdict']=='pass' and r['allow_provisional_basis'] and r['provisional_rationale'] for r in scope_reviews):reasons.append('PROVISIONAL_BASIS_NOT_ACCEPTED')
        if time_value(case['contract']['budget']['deadline'])<=now:reasons.append('BUDGET_DEADLINE')
    return {'boundary_passed_under_declared_inputs':not reasons,'reasons':sorted(set(reasons)),
            'execution_performed':False,'external_identity_authentication':'outside_this_module',
            'semantic_safety_established':False}
