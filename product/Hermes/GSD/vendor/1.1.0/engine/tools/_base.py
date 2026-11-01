"""GSD 3.0 / базовые проверки, перенесённые из DDx 2.0: договоры данных, межобъектные ограничения и процедурная очередь.

Содержательные операции исполняет агент. Этот модуль не вызывает модель,
не проверяет физическую истину и никогда не исполняет внешнее действие.
Зависимость: jsonschema (Draft 2020-12). Фактически испытанная версия Python
указана в отчёте; другая версия требует повторной проверки.
"""
from __future__ import annotations
from functools import lru_cache
import argparse
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('eMVP','MVP','Standard','eStandard','High Stakes','Critical Infrastructure')
TERMINAL = frozenset(('pass','limited','not_applicable'))
RISK_KEYS = ('assessed','critical_operational_use','safety_related_decision',
             'substantial_irreversible_consequences','complex_identification')

@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    detail: str

def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Повтор ключа JSON: {key}')
        result[key] = value
    return result

def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=_no_duplicate_keys,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Недопустимое число: {x}')))

def canonical(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def time_value(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None:
        raise ValueError('Требуется часовой пояс')
    return value.astimezone(timezone.utc)

def choose_profile(requested: str, risk: Mapping[str, Any]) -> dict[str, Any]:
    if requested not in PROFILES:
        raise ValueError('Неизвестный профиль')
    for key in RISK_KEYS:
        if key not in risk or (risk[key] is not None and type(risk[key]) is not bool):
            raise ValueError(f'{key}: требуется true, false или null; отсутствие не равно false')
    floor = 0
    reasons: list[str] = []
    if risk['complex_identification'] is True:
        floor = 3; reasons.append('Сложная идентификация')
    if risk['safety_related_decision'] is True or risk['substantial_irreversible_consequences'] is True:
        floor = max(floor,4); reasons.append('Значимые последствия или безопасность')
    if risk['critical_operational_use'] is True:
        floor = 5; reasons.append('Эксплуатационное влияние на критическую систему')
    unknown = risk['assessed'] is not True or any(risk[k] is None for k in RISK_KEYS[1:])
    if unknown:
        reasons.append('Оценка риска неполна; самостоятельное действие не разрешено')
    selected = PROFILES[max(PROFILES.index(requested),floor)]
    return {'requested':requested,'selected':selected,'required_floor':PROFILES[floor],
            'risk_incomplete':unknown,'reasons':reasons,'action_authority':'not_granted'}

def has_cycle(nodes: Iterable[str], edges: Iterable[tuple[str,str]]) -> bool:
    graph={n:[] for n in nodes}
    for a,b in edges:
        if a in graph and b in graph: graph[a].append(b)
    color: dict[str,int]={}
    # Iterative DFS avoids recursion failure on long but valid provenance chains.
    for root in graph:
        if color.get(root,0): continue
        stack=[(root,False)]
        while stack:
            n,exiting=stack.pop()
            if exiting: color[n]=2; continue
            if color.get(n,0)==1: return True
            if color.get(n,0)==2: continue
            color[n]=1;stack.append((n,True))
            for child in graph[n]:
                if color.get(child,0)==1:return True
                if color.get(child,0)==0:stack.append((child,False))
    return False

@lru_cache(maxsize=1)
def compiled_validator():
    import jsonschema
    schema=load_json(ROOT/'data/case.schema.json')
    return jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())

def base_validate_case(case: Any, *, now: datetime | None=None) -> list[Issue]:
    """Структура и объявленные межобъектные договоры. Не семантическая гарантия."""
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError('jsonschema отсутствует: проверка НЕ выполнена') from exc
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('now требует часового пояса')
    validator=compiled_validator()
    errors=[Issue('SCHEMA','/'.join(map(str,e.absolute_path)),e.message) for e in validator.iter_errors(case)]
    if errors:return errors  # Нет небезопасного обращения к некорректной структуре.
    out: list[Issue]=[]
    def err(code: str,path: str,detail: str)->None:out.append(Issue(code,path,detail))
    collections=('contexts','sources','evidence','claims','relations','models','genesis','tests',
                 'authorities','reviews','artifacts','source_applications','decisions')
    seen:dict[str,str]={}
    for name in collections:
        for item in case[name]:
            key=item['id']
            if key in seen:err('DUPLICATE_ID',name,key+' повторяет '+seen[key])
            seen[key]=name
    if out:return out
    maps={name:{x['id']:x for x in case[name]} for name in collections}
    contexts=maps['contexts']; sources=maps['sources']; evidence=maps['evidence']; claims=maps['claims']
    def exists(key: str,group: str,path: str)->bool:
        if key not in maps[group]:err('MISSING_REF',path,f'{key} отсутствует в {group}');return False
        return True
    def check_refs(keys: Iterable[str],group: str,path: str)->None:
        for key in keys:exists(key,group,path)
    def usable(eid: str)->bool:
        if eid not in evidence:return False
        e=evidence[eid];s=sources.get(e['source_id'])
        return bool(s and e['observation_state']=='observed' and s['availability']=='available'
                    and s['verification_status']=='checked' and s['kind']!='model'
                    and (case['data_kind']=='synthetic' or (s['kind']!='synthetic' and e['mode']!='synthetic')))
    for ctx in contexts.values():
        check_refs(ctx['standard_source_ids'],'sources',ctx['id'])
        ts=ctx['time_scope']
        if ts['start'] and ts['end'] and time_value(ts['start'])>time_value(ts['end']):
            err('TIME_ORDER',ctx['id'],'Начало позже окончания')
    for s in sources.values():check_refs(s['derived_from'],'sources',s['id'])
    if has_cycle(sources,[(s['id'],p) for s in sources.values() for p in s['derived_from']]):
        err('SOURCE_CYCLE','sources','Цикл происхождения источников')
    for e in evidence.values():
        exists(e['source_id'],'sources',e['id']);exists(e['context_id'],'contexts',e['id'])
        if e['transformation']:check_refs(e['transformation']['input_evidence_ids'],'evidence',e['id'])
        if e['mode']=='derived' and not e['transformation']:err('NO_TRANSFORM',e['id'],'Производное свидетельство без преобразования')
    if has_cycle(evidence,[(e['id'],p) for e in evidence.values() if e['transformation'] for p in e['transformation']['input_evidence_ids']]):
        err('EVIDENCE_CYCLE','evidence','Круговая цепь преобразования')
    for c in claims.values():
        cid=c['id'];j=c['J'];v=c['T']['verification'];m=c['M'];ct=c['C']
        exists(ct['context_id'],'contexts',cid);check_refs(c['S']['source_ids'],'sources',cid)
        for key in ('premise_ids','alternative_claim_ids','defeater_ids','unresolved_defeater_ids'):check_refs(j[key],'claims',cid)
        check_refs(j['evidence_ids'],'evidence',cid);check_refs(v['result_evidence_ids'],'evidence',cid)
        if not set(j['unresolved_defeater_ids'])<=set(j['defeater_ids']):
            err('DEFEATER_SET',cid,'Неразрешённое возражение отсутствует в наборе возражений')
        used=set(j['evidence_ids'])|set(v['result_evidence_ids'])
        for dim in ('V','A','R'):
            ass=j[dim];check_refs(ass['basis_evidence_ids'],'evidence',cid+'/J/'+dim);used.update(ass['basis_evidence_ids'])
            if ass['state']=='pass' and (not ass['basis_evidence_ids'] or not all(usable(e) for e in ass['basis_evidence_ids'])):
                err('UNSUPPORTED_DIMENSION',cid+'/J/'+dim,'Успешная координата требует пригодного адресуемого основания')
            if ass['state']=='not_applicable' and ass['required_for_use']:
                err('REQUIRED_NA',cid+'/J/'+dim,'Обязательная координата не может быть неприменимой')
        for eid in used:
            if eid in evidence and evidence[eid]['source_id'] not in c['S']['source_ids']:
                err('SOURCE_J_MISMATCH',cid,'Источник основания '+eid+' не указан в S')
        if v['status']=='completed':
            if v['outcome'] not in ('supports','opposes','inconclusive') or not v['result_evidence_ids']:
                err('VERIFICATION_NO_RESULT',cid,'Завершённая проверка требует исхода и реального результата')
        elif v['status']=='invalid':
            if v['outcome']!='invalid':err('INVALID_TEST_OUTCOME',cid,'Невалидный тест не равен отрицательному')
        elif v['status']=='stale':
            pass  # Исторический результат сохранён, активное использование отозвано.
        elif v['outcome'] is not None or v['result_evidence_ids']:
            err('UNRUN_RESULT',cid,'Невыполненная проверка не имеет фактического результата')
        supported=m['epistemic_status']=='supported'
        if supported:
            ctx=contexts.get(ct['context_id']);dims=set(ctx['required_dimensions']) if ctx else {'V','A','R'}
            dims|={dim for dim in ('V','A','R') if j[dim]['required_for_use']}
            if any(j[dim]['state']!='pass' for dim in dims):err('PROMOTION_J',cid,'Обязательный J не пройден')
            if not j['evidence_ids'] or not all(usable(e) for e in j['evidence_ids']):err('PROMOTION_EVIDENCE',cid,'Нет пригодного основания для supported')
            if v['status']!='completed' or v['outcome']!='supports':err('PROMOTION_T',cid,'T не поддерживает повышение')
            if m['evidence_state'] in ('both','neither','opposition_only') or j['unresolved_defeater_ids']:
                err('PROMOTION_CONFLICT',cid,'Конфликт или отсутствие поддержки запрещают supported')
            if ctx and ctx['expires_at'] and time_value(ctx['expires_at'])<=now:err('EXPIRED_CONTEXT',cid,'Срок контекста истёк')
        if supported:
            gates={r['gate'] for r in case['reviews'] if r['target_claim_id']==cid and r['execution_state']=='completed' and r['verdict']=='pass' and r.get('lifecycle')=='active'}
            required_gates={'G01'}
            required_gates.update({'causal':'G02','forecast':'G04','normative':'G08','recommendation':'G05'}.get(c['P']['kind'],'').split())
            if not required_gates<=gates:err('PROMOTION_GATE',cid,'Не пройдены требуемые G: '+','.join(sorted(required_gates-gates)))
        if m['evidence_state']=='both' and m['epistemic_status'] not in ('contested','hypothesis','unassessed','superseded'):
            err('CONFLICT_STATUS',cid,'both требует видимого конфликтного или предварительного статуса')
        if m['epistemic_status']=='refuted' and (v['status']!='completed' or v['outcome']!='opposes'):
            err('REFUTED_WITHOUT_TEST',cid,'Отвод версии не равен опровержению')
        p=m['probability']
        if p:
            exists(p['model_id'],'models',cid);check_refs(p['basis_evidence_ids'],'evidence',cid)
            if p['lower']>p['upper']:err('PROBABILITY_INTERVAL',cid,'Обратный интервал вероятности')
            model=maps['models'].get(p['model_id'])
            if model and model['kind']!='probability':err('PROBABILITY_MODEL',cid,'Не указан вероятностный тип модели')
            if m['modality']!='probabilistic':err('PROBABILITY_MODALITY',cid,'Вероятность требует probabilistic')
        if m['modality']=='probabilistic' and p is None:err('PROBABILITY_MISSING',cid,'Численная модальность без модели вероятности')
        if ct['transport_from_claim_id']:
            exists(ct['transport_from_claim_id'],'claims',cid)
            rid=ct['transport_review_id']
            if rid is None:err('TRANSPORT_NO_REVIEW',cid,'Перенос без отдельной проверки')
            elif exists(rid,'reviews',cid):
                rv=maps['reviews'][rid]
                if rv['gate']!='TRANSPORT' or rv['target_claim_id']!=cid:err('TRANSPORT_WRONG_REVIEW',cid,'Проверка относится к другому переходу')
                if supported and not (rv['execution_state']=='completed' and rv['verdict']=='pass'):
                    err('TRANSPORT_NOT_PASSED',cid,'Перенесённый supported требует пройденной проверки')
    if has_cycle(claims,[(c['id'],p) for c in claims.values() for p in c['J']['premise_ids']]):
        err('JUSTIFICATION_CYCLE','claims','Круговое обоснование посылками')
    for rel in maps['relations'].values():
        for k in ('from_id','to_id','claim_id'):exists(rel[k],'claims',rel['id'])
        exists(rel['context_id'],'contexts',rel['id'])
        assertion=claims.get(rel['claim_id'])
        if rel['status']=='supported' and assertion and assertion['M']['epistemic_status']!='supported':
            err('EDGE_PROMOTION',rel['id'],'Отношение сильнее утверждения о нём')
        if rel['type']=='causes' and assertion and assertion['P']['kind']!='causal':
            err('CAUSAL_EDGE_TYPE',rel['id'],'Причинное ребро требует причинного Claim')
    for model in maps['models'].values():
        exists(model['context_id'],'contexts',model['id']);check_refs(model['claim_ids'],'claims',model['id']);check_refs(model['relation_ids'],'relations',model['id'])
        rels=[maps['relations'][rid] for rid in model['relation_ids'] if rid in maps['relations']]
        for edge in rels:
            if edge['from_id'] not in model['claim_ids'] or edge['to_id'] not in model['claim_ids']:
                err('MODEL_EDGE_OUTSIDE',model['id'],'Конец ребра отсутствует в узлах модели')
        if model['kind'] in ('dag','tree'):
            if has_cycle(model['claim_ids'],[(r['from_id'],r['to_id']) for r in rels]):err('GRAPH_CYCLE',model['id'],'Цикл в ацикличной модели')
        if model['kind']=='tree':
            parents={n:[] for n in model['claim_ids']}
            for rel in rels:
                if rel['to_id'] in parents:parents[rel['to_id']].append(rel['from_id'])
            roots=[n for n,p in parents.items() if not p]
            if len(roots)!=1 or any(len(p)!=1 for n,p in parents.items() if n not in roots):
                err('TREE_PARENT',model['id'],'Дерево требует одного корня и одного родителя остальных узлов')
    for pos in case['positions']:
        exists(pos['claim_id'],'claims','positions');exists(pos['model_id'],'models','positions');exists(pos['context_id'],'contexts','positions');check_refs(pos['basis_claim_ids'],'claims','positions')
    for g in case['genesis']:
        exists(g['context_id'],'contexts',g['id']);check_refs(g['claim_ids'],'claims',g['id']);check_refs(g['event_evidence_ids'],'evidence',g['id'])
    for t in case['tests']:
        for field in ('question_claim_id','applicability_claim_id','cost_risk_claim_id'):exists(t[field],'claims',t['id'])
        check_refs(t['competitor_claim_ids'],'claims',t['id']);check_refs(t['result_evidence_ids'],'evidence',t['id'])
        if t['authority_id']:exists(t['authority_id'],'authorities',t['id'])
        if t['status']=='completed' and not t['result_evidence_ids']:err('TEST_NO_RESULT',t['id'],'Завершённый тест без результата')
    for authority in maps['authorities'].values():
        exists(authority['context_id'],'contexts',authority['id']);check_refs(authority['verification_evidence_ids'],'evidence',authority['id']);check_refs(authority['policy_source_ids'],'sources',authority['id'])
        if authority['verification']=='externally_verified' and (not authority['verification_evidence_ids'] or not all(usable(e) for e in authority['verification_evidence_ids'])):
            err('AUTHORITY_NO_EVIDENCE',authority['id'],'Нет пригодного свидетельства внешней проверки')
    for rv in maps['reviews'].values():
        exists(rv['target_claim_id'],'claims',rv['id']);check_refs(rv['evidence_ids'],'evidence',rv['id'])
        if rv.get('lifecycle')!='active':continue
        if rv['execution_state']=='completed':
            if rv['verdict'] is None:err('REVIEW_NO_VERDICT',rv['id'],'Завершённая проверка без исхода')
            if not rv['evidence_ids']:err('REVIEW_NO_BASIS',rv['id'],'Строка «проверено» не заменяет свидетельство')
            if rv['verdict']=='pass' and not all(usable(e) for e in rv['evidence_ids']):err('REVIEW_BAD_BASIS',rv['id'],'Непригодное основание pass')
        elif rv['verdict'] is not None:err('REVIEW_UNRUN_PASS',rv['id'],'Незавершённая проверка не имеет исхода')
        wa=rv['waiver']
        if rv['verdict']=='waived':
            if not wa:err('WAIVER_MISSING',rv['id'],'Исключение без записи')
            else:
                exists(wa['authority_id'],'authorities',rv['id']);check_refs(wa['policy_evidence_ids'],'evidence',rv['id']);check_refs(wa['compensating_claim_ids'],'claims',rv['id'])
                if time_value(wa['expires_at'])<=now:err('WAIVER_EXPIRED',rv['id'],'Исключение истекло')
                if rv['gate'] in ('PTJSMC','TRANSPORT'):err('EPISTEMIC_WAIVER',rv['id'],'Смысловая истинность и перенос не исключаются полномочием')
        elif wa:err('WAIVER_SPURIOUS',rv['id'],'Запись исключения без waived')
        if rv['gate']=='G02' and rv['verdict']=='pass':
            c=claims.get(rv['target_claim_id'])
            if c and c['P']['kind']=='causal' and not c['J']['alternative_claim_ids']:
                err('CAUSE_NO_ALTERNATIVE',rv['id'],'Причинный проход без адресуемой альтернативы')
    for art in maps['artifacts'].values():
        exists(art['context_id'],'contexts',art['id']);check_refs(art['claim_ids'],'claims',art['id']);check_refs(art['evidence_ids'],'evidence',art['id'])
    original_contracts={}
    if maps['source_applications']:
        for x in load_json(ROOT/'data/corpus_registry.json')['contracts']:
            for key in [x['key'],*x.get('aliases',[])]:original_contracts[key]=x
    for ap in maps['source_applications'].values():
        check_refs(ap['target_claim_ids'],'claims',ap['id']);check_refs(ap['result_artifact_ids'],'artifacts',ap['id'])
        if ap['status']=='applied' and not ap['result_artifact_ids']:err('SOURCE_NOMINAL_APPLICATION',ap['id'],'Применено без результата')
        original=original_contracts.get(ap['source_element_key'])
        if not original:err('SOURCE_ELEMENT_UNKNOWN',ap['id'],'Элемент отсутствует в объявленной версии корпуса')
        elif ap['source_hash']!=original['source_sha256'] or ap['exact_text']!=original['exact_text']:
            err('SOURCE_ELEMENT_MISMATCH',ap['id'],'Формулировка или версия исходника подменена')
        for ref_id in ap['input_refs']:
            if ref_id not in seen:err('MISSING_REF',ap['id'],'Отсутствующий вход '+ref_id)
        if ap['status']=='applied' and not ap['target_claim_ids']:
            err('SOURCE_NOMINAL_APPLICATION',ap['id'],'Нет целевого утверждения для фактического применения')
    for decision in maps['decisions'].values():
        check_refs(decision['basis_claim_ids'],'claims',decision['id']);check_refs(decision['execution_evidence_ids'],'evidence',decision['id']);exists(decision['context_id'],'contexts',decision['id'])
        if decision['authority_id']:exists(decision['authority_id'],'authorities',decision['id'])
        if decision['status'] in ('authorized','sent','executed') and not decision['authority_id']:err('ACTION_NO_AUTHORITY',decision['id'],'Действие без внешнего полномочия')
        if decision['status']=='executed' and not decision['execution_evidence_ids']:err('EXECUTED_NO_RECEIPT',decision['id'],'Нет свидетельства исполнения')
    route=choose_profile(case['requested_profile'],case['risk'])
    if route['risk_incomplete'] and any(d['status'] in ('authorized','sent','executed') for d in case['decisions']):
        err('ACTION_RISK_UNKNOWN','decisions','Исполнение при неполной оценке риска')
    if case['status'] in ('ready_for_review','closed'):
        if not claims:err('EMPTY_COMPLETION','status','Нет ни одного эпистемического атома')
        if case['status']=='closed' and any(d['status']=='outcome_unknown' for d in case['decisions']):
            err('CLOSED_UNKNOWN_ACTION','status','Неизвестный исход действия не закрыт')
    return out
