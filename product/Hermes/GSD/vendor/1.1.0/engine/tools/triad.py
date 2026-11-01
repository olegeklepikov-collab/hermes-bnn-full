"""Три самостоятельных интерфейса G/S/D и композиция всех семи режимов.

Встроены узкие проверяемые операции: конечное варьирование/комбинирование,
дедукция modus ponens и сравнение явно заданных предсказаний с наблюдениями.
Свободное порождение выполняет внешний агент-поставщик, а не фиктивный ответ
контроллера. Совпадение предсказаний не объявляется причинной истиной.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from itertools import product,combinations
from typing import Any,Callable,Mapping,Iterable
import argparse,json
from pathlib import Path
from records import digest,canonical,time_value,load_json,ROOT,PROFILES,choose_profile,RISK_KEYS

KINDS=frozenset(('idea','frame','question','concept','hypothesis','model','scenario','test','action'))
COMPONENTS=frozenset('GSD')
PROTOCOL='3.0'

def require_text(x,name):
    if not isinstance(x,str) or not x.strip():raise ValueError(name+': требуется содержательная строка')
def require_keys(x,required,allowed=None):
    if not isinstance(x,dict) or not set(required)<=set(x):raise ValueError('Неполный договор: '+','.join(sorted(set(required)-set(x if isinstance(x,dict) else {}))))
    if allowed is not None and not set(x)<=set(allowed):raise ValueError('Неизвестные поля: '+','.join(sorted(set(x)-set(allowed))))

def validate_candidate(c):
    keys=('id','version','kind','content','seed','operator_id','axis','frame','distinguishing_features','conditions',
          'claim_ids','status','expectations','scope','parent_ids','miss_risk','projections')
    require_keys(c,keys,keys)
    for k in ('id','seed','operator_id','axis','frame','scope'):require_text(c[k],k)
    if type(c['version']) is not int or c['version']<1:raise ValueError('Неверная версия кандидата')
    if c['kind'] not in KINDS or c['status'] not in ('candidate','withdrawn'):raise ValueError('G не устанавливает истинность продукта')
    if not isinstance(c['content'],dict) or not c['content']:raise ValueError('Нет типизированного содержимого')
    if not isinstance(c['expectations'],dict):raise ValueError('Следствия должны быть отображением')
    if c['miss_risk'] not in ('ordinary','high','unknown'):raise ValueError('Неверная цена пропуска')
    for k in ('distinguishing_features','conditions','claim_ids','parent_ids'):
        if not isinstance(c[k],list) or any(not isinstance(v,str) or not v.strip() for v in c[k]):raise ValueError('Неверное '+k)
    if not c['distinguishing_features']:raise ValueError('Не указано содержательное отличие')
    if c['status']=='withdrawn' and not c['content'].get('withdrawal_reason'):raise ValueError('Отвод требует причины, не молчаливого удаления')
    if c['kind']=='question' and not c['content'].get('question'):raise ValueError('Вопрос-кандидат должен содержать вопрос, не утверждение ответа')
    if c['kind']=='scenario' and c['content'].get('modality') not in (None,'possible','conditional'):raise ValueError('Сценарий не является прогнозом')
    if c['operator_id'].startswith(('GC-D','GA-08','GA-09')):
        a=c['content'].get('analogy',{})
        if not all(a.get(k) for k in ('source_domain','target_domain','mapping','breakpoints')):raise ValueError('Аналогия без структуры и границы переноса')
    if c['content'].get('mode_id')=='GM9' and not c['content'].get('stimulus_anchor'):raise ValueError('Нет обратной привязки случайного стимула к задаче')
    # Validate registered identity without pretending that it proves the move.
    from corpus import Corpus
    entries=Corpus().lookup('generative',c['operator_id'])
    if not any(e['role']=='generation' for e in entries):raise ValueError('Качество, способ, статус или контроль не подменяет производящий оператор')
    return True

def candidate_signature(c):
    # Labels/IDs are not diversity. A declared structural representation is compared
    # exactly; semantic equivalence of arbitrary prose remains an agent review.
    return digest({'kind':c['kind'],'structure':c['content'].get('structure',c['content']),
                   'expectations':c['expectations'],'conditions':sorted(c['conditions']),'scope':c['scope']})

def residuals(text='Не рассмотрены все возможные оси и механизмы'):
    return {'unsearched':text,'unexplained':'Относится к последующему предметному сравнению',
            'unknown':'Предметная истинность кандидатов не установлена генератором',
            'risk':'Остаточная опасность оценивается отдельно от числа кандидатов'}

class GenerationComponent:
    name='G';version='3.0'
    def run(self,request:Mapping[str,Any],*,provider:Callable|None=None):
        req=deepcopy(dict(request))
        required=('id','task','product_kind','seed','scope','frame','constraints','method','max_candidates','scan_budget')
        allowed=required+('axes','forbidden_combinations','supplied_candidates','known_candidates','adversarial','ga_results')
        require_keys(req,required,allowed)
        for k in ('id','task','seed','scope','frame'):require_text(req[k],k)
        if req['product_kind'] not in KINDS:raise ValueError('Неверный продукт генерации')
        if type(req['max_candidates']) is not int or req['max_candidates']<1 or type(req['scan_budget']) is not int or req['scan_budget']<1:raise ValueError('Нужен конечный бюджет генерации')
        if not isinstance(req['constraints'],list):raise ValueError('Ограничения задаются явно')
        candidates=[];scanned=0;applications=[];duplicate_ids=[];rejected=[]
        if req['method'] in ('variation','morphological'):
            axes=req.get('axes',{})
            if not axes or any(not isinstance(v,list) or not v for v in axes.values()):raise ValueError('Оси и их значения обязательны')
            if req['method']=='variation' and len(axes)!=1:raise ValueError('Варьирование здесь изменяет ровно одну ось')
            names=sorted(axes);op='GC-A003' if req['method']=='variation' else 'GC-F002'
            theoretical=1
            for v in axes.values():theoretical*=len(v)
            for vals in product(*(axes[k] for k in names)):
                if scanned>=req['scan_budget'] or len(candidates)>=req['max_candidates']:break
                scanned+=1;structure=dict(zip(names,vals))
                bad=next((rule for rule in req.get('forbidden_combinations',[]) if all(k in structure and canonical(structure[k])==canonical(v) for k,v in rule.items())),None)
                if bad is not None:rejected.append({'structure':structure,'reason':'declared_incompatibility','constraint':bad});continue
                content={'structure':structure}
                if req['product_kind']=='question':content['question']=req['task']+' '+json.dumps(structure,ensure_ascii=False)
                c={'id':req['id']+'.K'+str(scanned),'version':1,'kind':req['product_kind'],'content':content,
                   'seed':req['seed'],'operator_id':op,'axis':','.join(names),'frame':req['frame'],
                   'distinguishing_features':[k+'='+json.dumps(structure[k],ensure_ascii=False) for k in names],
                   'conditions':list(req['constraints']),'claim_ids':[],'status':'candidate','expectations':{},
                   'scope':req['scope'],'parent_ids':[],'miss_risk':'unknown','projections':{}}
                candidates.append(c)
            applications.append({'operator_id':op,'input_id':req['id'],'candidate_ids':[c['id'] for c in candidates],
                                 'attempted':scanned,'theoretical_combinations':theoretical,'rejected':rejected,
                                 'unexamined_at_least':max(0,theoretical-scanned)})
        elif req['method']=='supplied':
            candidates=deepcopy(req.get('supplied_candidates',[]));scanned=len(candidates)
            if len(candidates)>req['max_candidates'] or scanned>req['scan_budget']:raise ValueError('Поставленный набор превышает действующий бюджет')
        elif req['method']=='agent':
            if provider is None:return {'component':'G','status':'awaiting_provider','request':req,'candidates':[],
                                       'residuals':residuals(),'missing':[{'component':'G','need':'Реальный исполнитель смыслового порождения'}]}
            candidates=deepcopy(provider(req));scanned=len(candidates)
            if scanned>min(req['max_candidates'],req['scan_budget']):raise ValueError('Поставщик превысил бюджет')
        else:raise ValueError('Неподдерживаемый метод генерации')
        ids=set();retained=[];reused=[];archived=[];structural_groups=[]
        known_by_id={};groups={}
        for known in req.get('known_candidates',[]):
            validate_candidate(known)
            if known['kind']!=req['product_kind'] or known['scope']!=req['scope']:
                raise ValueError('Известный кандидат относится к иному продукту или C')
            if known['id'] in known_by_id and digest(known_by_id[known['id']])!=digest(known):
                raise ValueError('Неоднозначная идентичность известного кандидата')
            known_by_id[known['id']]=known
        for c in candidates:
            validate_candidate(c)
            if c['kind']!=req['product_kind'] or c['scope']!=req['scope']:
                raise ValueError('Подменены тип продукта или область')
            if c['id'] in ids:raise ValueError('Повтор идентичности кандидата')
            ids.add(c['id'])
            if c['id'] in known_by_id and digest(known_by_id[c['id']])!=digest(c):
                raise ValueError('Изменён известный кандидат без отдельного договора версии')
            groups.setdefault(candidate_signature(c),[]).append(c)
            if req['method'] in ('supplied','agent'):
                applications.append({'operator_id':c['operator_id'],'input_id':req['id'],'candidate_ids':[c['id']],
                                     'witness':list(c['distinguishing_features']),'status':'candidate_received_not_generated_here' if req['method']=='supplied' else 'candidate_received_from_provider'})
        # Representative choice is a declared bookkeeping rule, not a truth ranking.
        # Do not change an existing candidate's risk/status under the same identity.
        # Distinct lifecycle/risk members remain recoverable in the group/archive.
        risk_order={'high':0,'unknown':1,'ordinary':2}
        def representative_order(c):
            return (0 if c['status']=='candidate' else 1,risk_order[c['miss_risk']],c['id'],c['version'])
        for signature,members in groups.items():
            known_matches=[c for c in known_by_id.values() if candidate_signature(c)==signature]
            current_by_id={c['id']:c for c in members}
            union={**{c['id']:c for c in known_matches},**current_by_id}
            # A matching known result may be reused, but must not disappear on the
            # G -> S/D boundary. Novelty and the active diagnostic field differ.
            def origin_order(c):
                base=representative_order(c)
                return base[:2]+(0 if c['id'] in known_by_id else 1,)+base[2:]
            target=min(union.values(),key=origin_order)
            known_rep=known_by_id.get(target['id'])
            representative=target
            if known_rep is None:retained.append(deepcopy(target))
            else:reused.append(deepcopy(target))
            for member in members:
                if known_rep is None and member['id']==representative['id']:continue
                duplicate_ids.append({'id':member['id'],'same_as':target['id'],
                    'reason':'known_same_structure_lifecycle_risk' if known_rep else 'same_declared_structure'})
                archived.append(deepcopy(member))
            structural_groups.append({'structure_digest':signature,
                'member_bindings':{c['id']:digest(c) for c in sorted(union.values(),key=lambda c:c['id'])},
                'representative_id':target['id'],'representative_origin':'known_reference' if known_rep else 'current_input',
                'active_member_ids':sorted(c['id'] for c in union.values() if c['status']=='candidate'),
                'withdrawn_member_ids':sorted(c['id'] for c in union.values() if c['status']=='withdrawn'),
                'declared_miss_risks':{c['id']:c['miss_risk'] for c in sorted(union.values(),key=lambda c:c['id'])},
                'selection_policy':'active_before_withdrawn; high_then_unknown_then_ordinary; prefer_known; stable_id_tie_break',
                'is_truth_ranking':False})
        ga=req.get('ga_results',[])
        if req.get('adversarial'):
            expected={f'GA-{i:02d}' for i in range(1,13)}
            if {x.get('operator_id') for x in ga}!=expected or len(ga)!=12:raise ValueError('Нужен отдельный результат применимости каждого GA-01…GA-12')
            for x in ga:
                require_keys(x,('operator_id','applicability','reason','candidate_ids'))
                require_text(x['reason'],'основание применимости GA')
                if x['applicability'] not in ('applied','not_applicable','no_candidate'):raise ValueError('Неверный статус GA')
                if not set(x['candidate_ids'])<=ids:raise ValueError('GA ссылается на отсутствующего кандидата')
                if x['applicability']=='applied' and not x['candidate_ids']:raise ValueError('Применённый GA без индивидуального выхода')
                if any(next(c for c in candidates if c['id']==i)['operator_id']!=x['operator_id'] for i in x['candidate_ids']):raise ValueError('Выход другого GA не закрывает применение')
        field=retained+reused
        selected=[c['id'] for c in field if c['status']=='candidate']
        frames={c['frame'] for c in field};is_hyp=req['product_kind']=='hypothesis'
        checks=[('GG01',bool(field),'Есть различимый результат по объявленной структуре'),
                ('GG02',len(frames)>1,'Различимость рамок; одна заданная рамка сохраняется как ограничение'),
                ('GG03',not is_hyp or len(field)>1 and all(c['expectations'] for c in field),'Несколько объяснений и различимые следствия'),
                ('GG04',True,'Для заявленной аналогии проверено наличие отображения и точки разрыва'),
                ('GG05',not duplicate_ids,'Переименование одинаковой объявленной структуры не считается новизной'),
                ('GG06',True,'Пространство и остаток сохранены; нет заявления об исчерпании мира'),
                ('GG07',True,'Отводы адресованы; отбор не назван опровержением'),
                ('GG08',all(c['status'] in ('candidate','withdrawn') for c in field),'Передаются кандидаты, не установленное знание')]
        reviews=[{'id':req['id']+'.'+gate,'version':1,'gate':gate,'candidate_bindings':{c['id']:digest(c) for c in field},
                  'outcome':'pass' if ok else 'limited','criterion':text,'scope':'declared_structure_only',
                  'semantic_validation':'requires_agent_or_domain_review'} for gate,ok,text in checks]
        out={'id':req['id']+'.G','version':1,'component':'G','type':'CandidateSet','protocol_version':PROTOCOL,
          'status':'awaiting_validation','request_digest':digest(req),'scope':req['scope'],
          'candidates':retained,'reused_candidates':reused,'archived_candidates':archived,'structural_groups':structural_groups,'generation_contract_version':'3.0.3','known_candidate_bindings':{k:digest(v) for k,v in known_by_id.items()},'applications':applications,'ga_results':ga,'reviews':reviews,
          'selection':{'selected_ids':selected,'not_selected':duplicate_ids+[{'id':c['id'],'reason':c['content']['withdrawal_reason']} for c in field if c['status']=='withdrawn'],'criterion':'Различимость по объявленной структуре; без ранга истинности'},
          'residuals':residuals(),'resource':{'attempted':scanned,'retained':len(retained),'reused':len(reused),'structural_groups':len(structural_groups),'count_is_not_quality':True}}
        phase_states=[('GS01','registered_request'),('GS02','declared_frames' if len(frames)>1 else 'limited_single_frame'),
                      ('GS03','declared_seed'),('GS04','computed_variations' if req['method'] in ('variation','morphological') else 'received_variations_not_created_here'),
                      ('GS05','typed_candidates'),('GS06','grouped_declared_structures'),('GS07','selected_candidates_not_truth'),
                      ('GS08','prepared_not_delivered'),('GS09','not_performed_by_generator'),('GS10','open_residual')]
        out['generation_run']={'id':req['id']+'.RUN','version':1,'type':'GenerationRun',
            'mode':req['method'],'request_digest':digest(req),'local_effects_only':True,
            'phase_records':[{'sequence':i,'source_status_id':gs,'state':state,'scope':'declared_generation_structure'} for i,(gs,state) in enumerate(phase_states)],
            'protocol_records':[{'protocol_id':f'GP{i:02d}','status':'checked_structural_boundary' if i in (1,3,4) else 'declared_local_steps' if i==2 else 'handoff_prepared_not_delivered',
                                 'truth_promoted':False} for i in range(1,6)]}
        return out


def validate_observation(o):
    required=('id','key','value','source_id','origin_group','state','method_valid','used_for_generation')
    require_keys(o,required,required)
    for k in ('id','key','source_id','origin_group'):require_text(o[k],k)
    if o['state'] not in ('observed','not_measured','invalid','unavailable'):raise ValueError('Неизвестное состояние наблюдения')
    if type(o['method_valid']) is not bool or type(o['used_for_generation']) is not bool:raise ValueError('Недопустимая метка проверки')

COMPARISON_CONTRACT = '3.0.2'


def confirmation_eligible(observation: Mapping[str, Any]) -> bool:
    """Пригодность данной регистрации; не доказательство независимости её источника."""
    return (observation['state'] == 'observed'
            and observation['method_valid'] is True
            and observation['used_for_generation'] is False)


def validate_comparison_inputs(candidates, observations, scope):
    require_text(scope, 'C')
    if not isinstance(candidates, list) or not isinstance(observations, list):
        raise ValueError('Кандидаты и наблюдения должны быть списками')
    for c in candidates:
        validate_candidate(c)
        if c['scope'] != scope:
            raise ValueError('Перенос кандидата в другой C требует отдельного договора')
    for o in observations:
        validate_observation(o)
        canonical(o['value'])  # Не допускает NaN/Infinity и непредставимые значения.
    if len({o['id'] for o in observations}) != len(observations):
        raise ValueError('Дубли наблюдений')
    if len({c['id'] for c in candidates}) != len(candidates):
        raise ValueError('Дубли идентичности кандидатов')


def comparison_fields(c, observations):
    """Один договор конечного сравнения для производителя S и проверки входа D.

    Непригодные и использованные при построении записи сохраняются, но не занимают
    место пригодного представителя группы. Сортировка ID выбирает представителя
    независимо от порядка доставки. Это не удостоверяет происхождение мира.
    """
    expected=c['expectations'];support=[];opposition=[];unknown=[];dependent=[];seen=set()
    if c['status'] != 'withdrawn':
        for o in sorted(observations, key=lambda item: item['id']):
            if o['key'] not in expected:
                continue
            if o['state'] != 'observed' or not o['method_valid']:
                unknown.append(o['id']);continue
            if not confirmation_eligible(o):
                dependent.append(o['id']);continue
            dependency_key=(o['origin_group'],o['key'],canonical(o['value']))
            if dependency_key in seen:
                dependent.append(o['id']);continue
            seen.add(dependency_key)
            if canonical(expected[o['key']])==canonical(o['value']):support.append(o['id'])
            else:opposition.append(o['id'])
    profile='both' if support and opposition else 'support_only' if support else 'opposition_only' if opposition else 'neither'
    status=('withdrawn_candidate' if c['status']=='withdrawn' else
            'conflicted_prediction' if opposition and support else
            'contradicted_prediction' if opposition else
            'compatible_prediction' if support else 'underdetermined')
    return dict(support=support, opposition=opposition, unknown=unknown,
                dependent=dependent, evidence_profile=profile, status=status)


def validate_comparison_review(review, candidates, observations, *, scope):
    """Закрытый межкомпонентный договор; не удостоверение автора или истины."""
    from jsonschema import Draft202012Validator
    from corpus import static_contract
    validate_comparison_inputs(candidates, observations, scope)
    schema=static_contract(ROOT/'data/comparison_review.schema.json')
    errors=sorted(Draft202012Validator(schema).iter_errors(review), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError('Неверный договор ComparisonReview: '+str(list(errors[0].path))+': '+errors[0].message)
    expected=digest({'candidates':candidates,'observations':observations,'scope':scope})
    if review['input_digest']!=expected or review['scope']!=scope:
        raise ValueError('Проверка другой версии, наблюдений или контекста')
    rows=review['rows'];by_id={r['candidate_id']:r for r in rows}
    if len(by_id)!=len(rows) or set(by_id)!={c['id'] for c in candidates}:
        raise ValueError('Не проверен полный переданный набор или повторена идентичность')
    obs_by_id={o['id']:o for o in observations}
    for c in candidates:
        r=by_id[c['id']]
        if r['candidate_digest']!=digest(c) or r['candidate_version']!=c['version']:
            raise ValueError('Устарел кандидат')
        used=[]
        for field in ('support','opposition','unknown','dependent'):
            if any(oid not in obs_by_id for oid in r[field]):
                raise ValueError('Отсутствует наблюдение в '+field)
            used.extend(r[field])
        if len(used)!=len(set(used)):
            raise ValueError('Одна запись использована в несовместимых ролях')
        actual=comparison_fields(c, observations)
        for field, value in actual.items():
            received=sorted(r[field]) if isinstance(value,list) else r[field]
            if received!=value:
                raise ValueError('Роль свидетельства или статус не соответствуют конечному договору: '+field)
        if r['T']['actual_result']!=actual['status'] or r['M']['status']!=actual['status'] or r['C']!=scope:
            raise ValueError('T/M/C не согласованы с результатом строки')
        sources={obs_by_id[oid]['source_id'] for oid in r['support']+r['opposition']}
        if set(r['S'])!=sources:
            raise ValueError('Источники строки не соответствуют её свидетельствам')
        strength=('not_evaluated_archived' if c['status']=='withdrawn' else 'compatibility_in_explicit_prediction_model')
        if r['claim_strength']!=strength:
            raise ValueError('Завышена сила вывода или утрачен архивный статус')
    return True


class StrictComponent:
    name='S';version='3.0'
    def compare(self,candidates,observations,*,scope):
        validate_comparison_inputs(candidates, observations, scope)
        rows=[]
        for c in candidates:
            fields=comparison_fields(c, observations);status=fields['status']
            rows.append({'candidate_id':c['id'],'candidate_version':c['version'],'candidate_digest':digest(c),
                        **fields,
                        'claim_strength':'not_evaluated_archived' if c['status']=='withdrawn' else 'compatibility_in_explicit_prediction_model',
                        'P':'Архивный кандидат не оценивается в активном сравнении' if c['status']=='withdrawn' else 'Соответствие явно заданных предсказаний доступным наблюдениям',
                        'T':{'procedure':'Каноническое JSON-сравнение после проверки пригодности и роли регистрации','actual_result':status},
                        'J':{'V':'Сопоставляются объявленные величины; предметный смысл требует внешней проверки',
                             'A':'Значения сверены без неявного преобразования типов или единиц',
                             'R':'Детерминированный выбор представителя группы; независимость мира не утверждается'},
                        'S':sorted({o['source_id'] for o in observations if o['id'] in fields['support']+fields['opposition']}),
                        'M':{'modality':'conditional','status':status,'not_causal_truth':True},'C':scope})
        return {'id':'S.'+digest({'c':candidates,'o':observations,'s':scope,'comparator':COMPARISON_CONTRACT})[:16],
                'version':2,'component':'S','type':'ComparisonReview','protocol_version':PROTOCOL,
                'comparison_contract_version':COMPARISON_CONTRACT,'scope':scope,
                'input_digest':digest({'candidates':candidates,'observations':observations,'scope':scope}),
                'rows':rows,'residuals':residuals('Новые объяснения не порождались строгой проверкой'),
                'validation_boundary':'Проверено точное соответствие объявленной модели; истинность гипотезы и подлинность источников не установлены'}

    def derive(self,premises,implications,*,scope):
        """Конечное modus ponens. Нет абдукции из следствия или новых наблюдений."""
        require_text(scope,'C');facts={};steps=[]
        all_ids=[x.get('id') for x in premises+implications]
        if len(set(all_ids))!=len(all_ids):raise ValueError('Идентичность посылки/правила должна быть уникальной')
        for p in premises:
            require_keys(p,('id','proposition','source','status'))
            if p['status'] not in ('given','assumption'):raise ValueError('Недопустимый статус посылки')
            for k in ('id','proposition','source'):require_text(p[k],k)
            if p['proposition'] in facts:continue
            facts[p['proposition']]={'id':p['id'],'proposition':p['proposition'],'source':p['source'],'conditional_on':[p['id']]}
        for rule in implications:
            require_keys(rule,('id','if','then','source'))
            for k in ('id','if','then','source'):require_text(rule[k],k)
        occupied_ids=set(all_ids);next_id=1
        for _ in range(len(implications)+1):
            made=False
            for rule in implications:
                if rule['if'] in facts and rule['then'] not in facts:
                    parents=facts[rule['if']]['conditional_on']+[rule['id']]
                    while 'DERIVED.'+str(next_id) in occupied_ids:
                        next_id+=1
                    output_id='DERIVED.'+str(next_id);occupied_ids.add(output_id);next_id+=1
                    out={'id':output_id,'proposition':rule['then'],'source':rule['source'],'conditional_on':parents}
                    facts[rule['then']]=out;steps.append({'rule':'modus_ponens','premise':facts[rule['if']]['id'],'implication':rule['id'],'output':out});made=True
            if not made:break
        return {'component':'S','type':'FormalDerivation','scope':scope,'facts':list(facts.values()),'steps':steps,
                'M':'Условный вывод в предъявленной системе; истинность посылок отдельно','residuals':residuals()}

    def principle_contract(self,proposal):
        """Проверка формы специальной исходной грамматики, не доказательство смысла."""
        from corpus import Corpus
        required=('id','statement','primary_C_ID','D_path','D_required_reason','M_path','M_required_reason',
                  'E_ID','Q_ID','register_profile','S0_pass_reason','H_role','H_not_used_for_validation','negative_grammar_hits')
        require_keys(proposal,required,required);c=Corpus()
        for k in ('id','statement','D_required_reason','M_required_reason','S0_pass_reason'):require_text(proposal[k],k)
        if not proposal['primary_C_ID'].startswith('C-'):raise ValueError('Нужен конкретный C-ID, не один предметный пример')
        c.lookup('strict',proposal['primary_C_ID']);c.lookup('strict',proposal['E_ID']);c.lookup('strict',proposal['Q_ID'])
        if not proposal['E_ID'].startswith('E') or not proposal['Q_ID'].startswith('Q'):raise ValueError('Неверный тип ошибки или качества')
        for field,prefix in [('D_path','D'),('M_path','M')]:
            if not isinstance(proposal[field],list) or not proposal[field] or any(not isinstance(v,str) or not v.startswith(prefix) for v in proposal[field]):raise ValueError('Нет пути '+field)
            for item in proposal[field]:c.lookup('strict',item)
        if not isinstance(proposal['register_profile'],dict) or set(proposal['register_profile'])!=set('OEAD'):raise ValueError('Неполный регистр O/E/A/D')
        for value in proposal['register_profile'].values():require_text(value,'Основание регистра')
        if proposal['H_role'] not in ('none','specialize_only') or proposal['H_not_used_for_validation'] is not True:raise ValueError('Предметное расширение не валидирует принцип')
        if proposal['negative_grammar_hits']!=[]:raise ValueError('Не снята отрицательная грамматика')
        return {'component':'S','type':'PrincipleDerivationContract','status':'well_formed_candidate',
                'input_digest':digest(proposal),'semantic_forward_derivability':'requires_independent_content_review',
                'registers_preserved':True,'M':'Правильная форма не доказывает необходимость D/M и истинность принципа'}

class DiagnosticComponent:
    name='D';version='3.0'
    def run(self,*,candidates,observations,scope,review=None,question):
        require_text(question,'Вопрос D');require_text(scope,'C')
        validate_comparison_inputs(candidates, observations, scope)
        missing=[]
        if not candidates:missing.append({'component':'G','need':'Различимые версии или внешняя поставка кандидатов'})
        if review is None:missing.append({'component':'S','need':'Проверка текущих версий и оснований'})
        if missing:return {'component':'D','type':'DiagnosticResult','status':'partial','question':question,'scope':scope,
                           'missing':missing,'candidates':deepcopy(candidates),'residuals':residuals(),'action_authorized':False}
        validate_comparison_review(review,candidates,observations,scope=scope)
        rows=review['rows']
        active=[c for c in candidates if c['status']=='candidate']
        archived=[deepcopy(c) for c in candidates if c['status']=='withdrawn']
        compatible=[r['candidate_id'] for r in rows if r['status'] in ('compatible_prediction','underdetermined')]
        contradicted=[r['candidate_id'] for r in rows if r['status'] in ('contradicted_prediction','conflicted_prediction')]
        observed={o['key'] for o in observations if confirmation_eligible(o)}
        discriminators=[]
        for a,b in combinations([c for c in active if c['id'] in compatible],2):
            for k in sorted(set(a['expectations'])&set(b['expectations'])-observed):
                if canonical(a['expectations'][k])!=canonical(b['expectations'][k]):discriminators.append({'question_key':k,'a':a['id'],'expected_a':a['expectations'][k],'b':b['id'],'expected_b':b['expectations'][k],
                    'kind':'independent_confirmation' if any(o['key']==k and o['used_for_generation'] for o in observations) else 'measurement',
                    'prior_observation_ids':[o['id'] for o in observations if o['key']==k],
                    'availability':'not_established','action':'Получить допустимое независимое наблюдение; не выдавать план за результат'})
        return {'component':'D','type':'DiagnosticResult','status':'bounded_comparison','question':question,'scope':scope,
          'compatible_in_model':compatible,'contradicted_in_model':contradicted,'discriminators':discriminators,
          'archived_candidates':archived,
          'identification':'not_established' if len(compatible)!=1 else 'one_compatible_in_enumerated_model_not_proven_cause',
          'orders':{'plausibility':'Не вычисляется из суммы совпадений','miss_priority':[c['id'] for c in active if c['miss_risk']=='high'],
                    'test_priority':[x['question_key'] for x in discriminators],'action_preference':'Отдельный договор потерь и полномочий'},
          'review_ref':review['id'],'residuals':residuals(),'action_authorized':False}


def execute_components(active,request,*,generation_provider=None,budget=None):
    active=set(active)
    if not active or not active<=COMPONENTS:raise ValueError('Нужен один из семи непустых составов G/S/D')
    risk=request.get('risk',{k:None for k in RISK_KEYS})
    route=choose_profile(request.get('requested_profile','eMVP'),risk)
    limits=request.get('execution_budget',{'step_limit':100,'reserve_steps':1})
    budget=budget or SharedBudget(limits['step_limit'],limits['reserve_steps'])
    result={'profile':route,'protocol_version':PROTOCOL,'active_components':sorted(active),'executed_components':[],'outputs':{}}
    candidates=deepcopy(request.get('candidates',[]));review=request.get('review')
    if active=={'S'} and request.get('operation') in ('derive','principle_contract'):
        operation=request['operation'];units=max(1,len(request.get('premises',[]))+len(request.get('implications',[])))
        key='S.'+digest(request)
        if not budget.allocate(key,units):raise ValueError('Результат этого S-запуска уже учтён')
        output=StrictComponent().derive(request['premises'],request['implications'],scope=request['scope']) if operation=='derive' else StrictComponent().principle_contract(request['proposal'])
        budget.settle(key,units);result['outputs']['S']=output;result['executed_components']=['S']
        result['resource']={'spent_local_units':budget.spent,'reserve_steps':budget.reserve,'measure':'Число локальных операций, не токены и не деньги'}
        result['unmet_profile_obligations']=['Нужна независимая предметная приемка'] if PROFILES.index(route['selected'])>=4 else []
        return result
    if 'G' in active:
        if not budget.allocate(request['generation']['id']+'.G',request['generation']['scan_budget']):raise ValueError('Результат этого G-запуска уже учтён; используйте сохранённый выход')
        g=GenerationComponent().run(request['generation'],provider=generation_provider);budget.settle(request['generation']['id']+'.G',g.get('resource',{}).get('attempted',0));result['outputs']['G']=g;result['executed_components'].append('G');candidates=g['candidates']+g.get('reused_candidates',[])
    if 'S' in active:
        units=max(1,len(candidates)*len(request.get('observations',[])))
        if not budget.allocate('S.'+digest(request),units):raise ValueError('Результат этого S-запуска уже учтён')
        s=StrictComponent().compare(candidates,request.get('observations',[]),scope=request['scope']);budget.settle('S.'+digest(request),units);result['outputs']['S']=s;result['executed_components'].append('S');review=s
    if 'D' in active:
        units=max(1,len(candidates)*(len(candidates)-1)//2)
        if not budget.allocate('D.'+digest(request),units):raise ValueError('Результат этого D-запуска уже учтён')
        d=DiagnosticComponent().run(candidates=candidates,observations=request.get('observations',[]),scope=request['scope'],review=review,question=request['question'])
        budget.settle('D.'+digest(request),units);result['outputs']['D']=d;result['executed_components'].append('D')
    result['resource']={'spent_local_units':budget.spent,'reserve_steps':budget.reserve,'measure':'Число ограниченных локальных операций; не токены и не денежная стоимость'}
    result['unmet_profile_obligations']=['Независимая предметная проверка и эксплуатационный допуск не выполняются узкими встроенными алгоритмами'] if PROFILES.index(route['selected'])>=4 else []
    return result

class SharedBudget:
    """Один бюджет в однопроцессной среде; конкурентная запись защищена блокировкой."""
    def __init__(self,limit,reserve=1):
        import threading
        if type(limit) is not int or type(reserve) is not int or not 0<=reserve<limit:raise ValueError('Неверный бюджет')
        self.limit=limit;self.reserve=reserve;self.spent=0;self.reservations={};self.history={};self._lock=threading.RLock()
    def allocate(self,key,amount):
        with self._lock:
            if type(amount) is not int or amount<0:raise ValueError('Неверный расход')
            if key in self.history:
                if self.history[key]!=amount:raise ValueError('Один ключ с иной суммой')
                return False
            if key in self.reservations:
                if self.reservations[key]!=amount:raise ValueError('Конфликт резерва')
                return False
            if self.spent+sum(self.reservations.values())+amount>self.limit-self.reserve:raise ValueError('Общий бюджет исчерпан')
            self.reservations[key]=amount;return True
    def settle(self,key,actual):
        with self._lock:
            if key not in self.reservations:raise ValueError('Нет действующего резерва')
            if type(actual) is not int or not 0<=actual<=self.reservations[key]:raise ValueError('Расход вне резерва')
            allocated=self.reservations.pop(key);self.spent+=actual;self.history[key]=allocated

def require_identifier(value, name):
    """Canonical lexical identity: no silent trimming, Unicode control or NFC repair."""
    import unicodedata
    require_text(value,name)
    if (value!=unicodedata.normalize('NFC',value)
            or any(c.isspace() or unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError(name+': требуется нормализованный идентификатор без пробелов и управляющих знаков')


def validate_handoff_header(message):
    """Closed wire contract; strict Python integer types supplement JSON Schema."""
    from jsonschema import Draft202012Validator
    # Schema parsing is cached on the function, never on untrusted payload content.
    if not hasattr(validate_handoff_header,'_validator'):
        schema=load_json(ROOT/'data/handoff.schema.json')
        Draft202012Validator.check_schema(schema)
        validate_handoff_header._validator=Draft202012Validator(schema)
    errors=list(validate_handoff_header._validator.iter_errors(message))
    if errors:raise ValueError('Неверный договор заголовка передачи: '+errors[0].message)
    if type(message['payload_version']) is not int or message['payload_version']<1:
        raise ValueError('Версия передачи должна быть положительным целым, не bool или float')
    if type(message['budget_amount']) is not int or message['budget_amount']<0:
        raise ValueError('Расход передачи должен быть неотрицательным целым')
    for key in ('id','sender','receiver','payload_id','budget_reservation'):
        require_identifier(message[key],key)
    for key in message['dependency_bindings']:require_identifier(key,'dependency_id')
    return True


class HandoffChannel:
    """Локальный приём сообщения: контекст/версия/срок проверяются до подавления повтора.
    Сетевой транспорт, идентичность сторон и хранение реализует внешняя среда.
    """
    def __init__(self,*,component_versions,corpus_digest,budget,risk_floor='eMVP'):
        self.component_versions=dict(component_versions);self.corpus_digest=corpus_digest;self.budget=budget;self.seen={};self.risk_floor=risk_floor;self.reservation_owner={}
    def send(self,message,*,objects,receiver,now=None):
        now=now or datetime.now(timezone.utc)
        required=('id','sender','receiver','protocol_version','component_versions','corpus_digest','payload_id','payload_version','payload_digest',
                  'dependency_bindings','context_digest','standard_digest','risk_floor','deadline','budget_reservation','budget_amount','allowed_effects','residuals','input_status')
        require_keys(message,required,required)
        validate_handoff_header(message)
        if not isinstance(objects,Mapping):raise ValueError('Объекты передачи должны быть отображением')
        if message['protocol_version']!=PROTOCOL or message['component_versions']!=self.component_versions or message['corpus_digest']!=self.corpus_digest:raise ValueError('Несовместимая версия передачи')
        if message['receiver']!=receiver or message['sender'] not in self.component_versions or receiver not in self.component_versions:raise ValueError('Неверный получатель или неподключённый поставщик')
        if message['allowed_effects'] not in ([],['local_analysis']):raise ValueError('Канал мыслительной передачи не делегирует внешние эффекты')
        if message['risk_floor'] in PROFILES and PROFILES.index(message['risk_floor'])<PROFILES.index(self.risk_floor):raise ValueError('Передача не снижает действующий уровень риска')
        if message['risk_floor'] not in PROFILES or not isinstance(message['residuals'],dict) or set(message['residuals'])!=set(residuals()):raise ValueError('Потерян профиль или остаток')
        if not all(isinstance(v,str) and v.strip() for v in message['residuals'].values()):raise ValueError('Пустой остаток')
        if time_value(message['deadline'])<=now:raise ValueError('Поздний пакет не наследует актуальное применение')
        payload=objects.get(message['payload_id'])
        if (not isinstance(payload,dict) or payload.get('id')!=message['payload_id']
                or type(payload.get('version')) is not int or payload['version']<1
                or payload['version']!=message['payload_version'] or digest(payload)!=message['payload_digest']):
            raise ValueError('Подменён объект сообщения или неоднозначна его идентичность')
        require_identifier(payload['id'],'payload.id')
        epistemic=payload.get('M',{})
        declared_status=payload.get('status') or (epistemic.get('epistemic_status') if isinstance(epistemic,dict) else None)
        if declared_status is None and message['input_status']!='unreviewed':
            raise ValueError('Продукт без собственного статуса передаётся только как unreviewed')
        if declared_status and declared_status!=message['input_status']:raise ValueError('Передача не изменяет входной эпистемический статус')
        if not isinstance(message['dependency_bindings'],dict):raise ValueError('Не определена карта зависимостей')
        for key,fp in message['dependency_bindings'].items():
            if key not in objects or digest(objects[key])!=fp:raise ValueError('Изменилась зависимость сообщения')
        if 'context' not in objects or digest(objects['context'])!=message['context_digest'] or 'standard' not in objects or digest(objects['standard'])!=message['standard_digest']:raise ValueError('Изменён C/стандарт')
        signature=digest(message)
        if message['id'] in self.seen:
            if self.seen[message['id']]['signature']!=signature:raise ValueError('Повтор ID с другим смыслом')
            return {**deepcopy(self.seen[message['id']]['receipt']),'duplicate':True}
        owner=self.reservation_owner.get(message['budget_reservation'])
        if owner is not None and owner!=message['id']:raise ValueError('Один резерв не оплачивает две разные передачи')
        if not self.budget.allocate(message['budget_reservation'],message['budget_amount']):raise ValueError('Резерв ранее использован другим обязательством')
        self.reservation_owner[message['budget_reservation']]=message['id']
        receipt={'id':message['id'],'state':'accepted_for_processing','epistemic_promotion':False,'effect_performed':False,'duplicate':False}
        self.seen[message['id']]={'signature':signature,'receipt':receipt};return receipt


def intake_raw(text,*,requested_components=('G','S','D')):
    require_text(text,'Сырой запрос')
    if not set(requested_components)<=COMPONENTS:raise ValueError('Неверный состав')
    return {'type':'RawInput','id':'RAW.'+digest(text)[:16],'version':1,'text':text,'components':list(requested_components),
            'state':'draft','trust':'untrusted_data','missing_fields':['контракт','источники','C','применимые P.T.J(V,A,R).S.M.C'],
            'next':'Сформировать достаточный вход ближайшей операции; не выдумывать полномочия','action_authorized':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('components',choices=['G','S','D','GS','GD','SD','GSD']);p.add_argument('request',type=Path)
    a=p.parse_args()
    try:result=execute_components(a.components,load_json(a.request));print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,OSError) as exc:print(json.dumps({'error':str(exc),'execution_completed':False},ensure_ascii=False));raise SystemExit(2)
