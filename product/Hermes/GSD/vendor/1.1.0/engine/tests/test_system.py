"""Проверки GSD v3. Искусственные данные; нет внешних эффектов и испытаний LLM.
Проверяется отказ на конкретное нарушение плюс допустимый близкий случай.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from itertools import product,combinations
import json,sys,time,hashlib,platform,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from engine import *
from triad import *
from migrate import migrate_v2
from corpus import Corpus
NOW=datetime(2026,9,12,tzinfo=timezone.utc)
BASE=load_json(ROOT/'examples/01_measurement_vs_process.json');MIN=load_json(ROOT/'examples/triggers_minimal.json')
RESULTS=[]
def check(condition,msg='Условие не выполнено'):
    if not condition:raise AssertionError(msg)
def must_raise(fn,contains=None):
    try:fn()
    except (ValueError,RuntimeError,KeyError) as exc:
        if contains:check(contains in str(exc),str(exc))
        return str(exc)
    raise AssertionError('Ожидался определённый отказ')
def codes(c):return {i.code for i in validate_case(c,now=NOW)}
def test(name,fn,category='contract',finding=None):
    if '--trace-profile' in sys.argv and category!='synthetic_controller_trace':return
    print('RUN',name,flush=True)
    start=time.perf_counter()
    try:
        detail=fn();RESULTS.append({'name':name,'passed':True,'category':category,'finding':finding,'seconds':time.perf_counter()-start,'detail':detail})
    except Exception as exc:
        RESULTS.append({'name':name,'passed':False,'category':category,'finding':finding,'seconds':time.perf_counter()-start,'error':type(exc).__name__+': '+str(exc),'trace':traceback.format_exc()})

def rebind(c):
    for r in c['reviews']:
        if r['lifecycle']=='active':r['binding']=review_binding(c,r['target_claim_id'],r['evidence_ids'])
    return c

def artifact(e,p,bind=None):
    cid=bind['claim_id'] if bind else 'P1'
    return {'id':'ART.'+p['id']+'.'+cid+'.'+str(len(e.case['artifacts'])),'version':1,'kind':p['output_type'],'context_id':'CTX1',
      'summary':'Искусственный выход: проверяется договор контроллера, не исполнение смысла всей процедуры.',
      'claim_ids':[cid],'evidence_ids':['E1'],'limitations':['synthetic_contract_fixture'],
      'target_version':bind['claim_version'] if bind else None,'target_digest':bind['claim_digest'] if bind else None,
      'input_fingerprint':e._fingerprint(p),'semantic_result_refs':[cid],'accepted_limitations_by':[]}

def commit_next(e,status='pass'):
    nxt=e.next_step();p=nxt['procedure']
    check(p is not None,'Нет доступного шага: '+str(nxt))
    arts=[artifact(e,p,b) for b in claim_bindings(e.case,p)] if p.get('execution_scope')=='each_claim' else [artifact(e,p)]
    c=deepcopy(e.case);c['revision']+=1;c['artifacts'].extend(arts)
    e.update_case(c,expected_revision=e.case['revision'])
    aid='RUN.'+str(len(e.events))
    result=e.commit(p['id'],aid,status,[x['id'] for x in arts],expected_revision=e.case['revision'],
             postcondition_observed='Проверены тип, адрес и версия искусственного результата; смысловая способность агента не испытывалась.',
             reason='Искусственное ограничение' if status=='limited' else '')
    return result,p['id'],aid

def finish(e,limit=400):
    count=0
    while e.next_step()['procedure'] is not None:
        commit_next(e);count+=1
        if count>limit:raise AssertionError('Зацикливание')
    check(e.state=='ready_for_review','Не достигнута готовность: '+str(e.next_step()))
    return count

# Schema and exact epistemic atom.
for path in sorted((ROOT/'examples').glob('0*.json')):
    test('Принят корректный пример '+path.name,lambda path=path:check(not codes(load_json(path)),str(codes(load_json(path)))),'positive')
for key in ['P','T','J','S','M','C']:
    def missing(key=key):
        c=deepcopy(BASE);del c['claims'][0][key];check('SCHEMA' in codes(c))
    test('Отсутствующий '+key+' не принимается',missing,'negative','F14')
for dim in ['V','A','R']:
    def unknown(dim=dim):
        c=deepcopy(BASE);c['claims'][0]['J'][dim]['state']='unknown';rebind(c);check('STRONG_J' in codes(c))
    test('Обязательный J.'+dim+' ограничивает сильный статус',unknown,'negative','F14')
for name,mut,code in [
 ('Пустой тезис',lambda c:c['claims'][0]['P'].__setitem__('text',' '),'SCHEMA'),
 ('Ложная модальность',lambda c:c['claims'][0]['M'].__setitem__('modality','certain_forever'),'SCHEMA'),
 ('Повтор ID',lambda c:c['claims'].append(deepcopy(c['claims'][0])),'DUPLICATE_ID'),
 ('Несуществующий источник',lambda c:c['claims'][0]['S']['source_ids'].append('LOST'),'MISSING_REF'),
 ('Непроведено с исходом',lambda c:c['claims'][0]['T']['verification'].__setitem__('status','planned'),'UNRUN_RESULT'),
 ('Неизмеренное T',lambda c:c['evidence'][0].__setitem__('observation_state','not_measured'),'T_UNUSABLE'),
 ('Просроченный C',lambda c:c['contexts'][0].__setitem__('expires_at','2020-01-01T00:00:00Z'),'EXPIRED_CONTEXT'),
 ('Устаревшая проверка',lambda c:c['claims'][0]['P'].__setitem__('text','Иное содержание без новой проверки'),'REVIEW_STALE_BINDING'),
 ('Подменённый Context',lambda c:c['contexts'][0].__setitem__('regime','Иной режим'),'REVIEW_STALE_BINDING'),
 ('Круговое обоснование',lambda c:c['claims'][0]['J']['premise_ids'].append('P1'),'JUSTIFICATION_CYCLE')]:
    def run(mut=mut,code=code):
        c=deepcopy(BASE);mut(c);cs=codes(c);check(code in cs,str(cs));return sorted(cs)
    test(name,run,'negative')

def ancestor():
    c=deepcopy(BASE);bad=deepcopy(c['sources'][0]);bad['id']='BAD';bad['verification_status']='retracted';c['sources'].append(bad);c['sources'][0]['derived_from']=['BAD'];rebind(c)
    check('J_CHAIN_UNUSABLE' in codes(c));return sorted(codes(c))
test('Отозванный предок не поддерживает потомка',ancestor,'regression','F11')

def refute_no_data():
    c=deepcopy(BASE);h=c['claims'][1];h['M'].update(epistemic_status='refuted',evidence_state='opposition_only');h['T']['verification'].update(status='completed',outcome='opposes',result_evidence_ids=['E1']);c['evidence'][0]['observation_state']='not_measured';rebind(c)
    check('STRONG_J' in codes(c) and 'STRONG_T' in codes(c))
test('Опровержение требует пригодных T и J',refute_no_data,'regression','F14')

def test_plan(c):
    t={'id':'TEST1','version':1,'question_claim_id':'H1','competitor_claim_ids':['H1','H2'],
       'method':'Искусственный различитель','outcome_rules':{'supports':'одна версия','opposes':'иная версия','inconclusive':'не различено','invalid':'ошибка метода'},
       'applicability_claim_id':'P1','cost_risk_claim_id':'P1','authority_id':None,'status':'planned','result_evidence_ids':[],'use_state':'active'}
    # Preserve exact original schema shape for outcome_rules.
    s=load_json(ROOT/'data/case.schema.json')['$defs']['test']['properties']['outcome_rules']
    if s.get('type')=='array':
        t['outcome_rules']=[{'outcome':k,'meaning':v} for k,v in t['outcome_rules'].items()]
    c['tests'].append(t);return t
# Test the exact fields from the original audit fixture.
def audit_test_plan(c):
    t={'id':'TEST1','version':1,'question_claim_id':'H1','competitor_claim_ids':['H1','H2'],
       'method':'Искусственная проверка','outcome_rules':{'positive':'H1','negative':'H2','inconclusive':'Не различено','invalid':'Ошибка метода'},
       'applicability_claim_id':'P1','cost_risk_claim_id':'P1','authority_id':None,'status':'planned','result_evidence_ids':[],'use_state':'active'}
    c['tests'].append(t);return t

def dep_question():
    c=deepcopy(BASE);t=audit_test_plan(c);result=dependency_impact(c,['H1']);check('TEST1' in result['tests']);return result['tests']
test('Вопрос и конкуренты достигают TestPlan',dep_question,'regression','F10')

# Profile invariants and executable queue.
def profile_property():
    n=0
    for req in PROFILES:
        for vals in product([False,True],repeat=5):
            risk=dict(zip(RISK_KEYS,vals));r=choose_profile(req,risk);n+=1
            check(PROFILES.index(r['selected'])>=PROFILES.index(req))
            if risk['critical_operational_use']:check(r['selected']=='Critical Infrastructure')
            check(r['action_authority']=='not_granted')
    check(n==192);return n
test('192 сочетания профиля и риска',profile_property,'property','F08')

def profile_update():
    c=deepcopy(BASE);c['requested_profile']='eMVP';e=ProcedureEngine(c,MIN);old=len(e.plan)
    c=deepcopy(e.case);c['revision']+=1;c['risk']['critical_operational_use']=True
    e.update_case(c,expected_revision=e.case['revision']);ids={x['procedure_id'] for x in e.plan}
    check(all(f'ASSURANCE.{i:02d}' in ids for i in range(1,9)));check(len(e.plan)>old);must_raise(lambda:e.close(criterion_record='Не разрешено закрывать прежним объёмом'))
    return {'old':old,'new':len(e.plan)}
test('Рост критичности пересобирает обязательства',profile_update,'regression','F08')

def false_action_trigger():
    c=deepcopy(BASE);c['contract']['intended_use']='authorized_execution';e=ProcedureEngine(c,MIN)
    check(all(f'DECISION.{i:02d}' in {p['procedure_id'] for p in e.plan} for i in range(1,8)))
test('false не выключает необходимое действие',false_action_trigger,'regression','F09')

def source_update():
    e=ProcedureEngine(BASE,MIN);commit_next(e)
    c=deepcopy(e.case);c['revision']+=1;c['evidence'][0]['version']+=1;c['evidence'][0]['content']='Изменённая первичная строка'
    e.update_case(c,expected_revision=e.case['revision'])
    check(e.case['claims'][0]['M']['epistemic_status']=='unassessed')
    check(e.case['reviews'][0]['lifecycle']=='stale')
    check(bool(e.pending_target_obligations()));check(not codes(e.case),str(codes(e.case)))
    return {'claim_status':e.case['claims'][0]['M']['epistemic_status'],'pending':len(e.pending_target_obligations())}
test('Изменение Evidence отзывает Claim и Review',source_update,'regression','F10')

def same_version_object():
    e=ProcedureEngine(BASE,MIN);c=deepcopy(e.case);c['revision']+=1;c['sources'][0]['locator']='Иной адрес'
    must_raise(lambda:e.update_case(c,expected_revision=e.case['revision']),'новой версии')
test('Источник нельзя менять без версии',same_version_object,'regression','F15')

def blocked_state():
    e=ProcedureEngine(BASE,MIN);c=deepcopy(e.case);c['revision']+=1;c['status']='blocked';e.update_case(c,expected_revision=e.case['revision'])
    check(e.state=='blocked' and e.next_step()['procedure'] is None and e.case['status']==e.state)
test('Согласованы состояния случая и контроллера',blocked_state,'regression','F12')

def stop_repair():
    e=ProcedureEngine(BASE,MIN);pid=e.next_step()['procedure']['id'];e.commit(pid,'FAIL1','needs_repair',[],expected_revision=e.case['revision'],postcondition_observed='Вход не принят',reason='Исправить вход')
    e.stop('Предел');must_raise(lambda:e.insert_repair(pid,reason='Не является новым допуском'));check(e.state=='partial')
test('Ремонт не возобновляет остановленный запуск',stop_repair,'regression','F12')

def revision_only_retry():
    e=ProcedureEngine(BASE,MIN);pid=e.next_step()['procedure']['id'];e.commit(pid,'FAIL1','needs_data',[],expected_revision=e.case['revision'],postcondition_observed='Данные отсутствуют',reason='Нет основания')
    c=deepcopy(e.case);c['revision']+=1;e.update_case(c,expected_revision=e.case['revision'])
    must_raise(lambda:e.commit(pid,'FAIL2','needs_data',[],expected_revision=e.case['revision'],postcondition_observed='Всё ещё отсутствуют',reason='Повтор'),'нового содержательного')
test('Номер ревизии не создаёт новый вход для повтора',revision_only_retry,'regression','F12')

def global_budget():
    c=deepcopy(BASE);c['contract']['budget']['step_limit']=3;c['contract']['budget']['reserve_steps']=1
    e=ProcedureEngine(c,MIN);commit_next(e);commit_next(e);must_raise(lambda:commit_next(e),'BUDGET_EXHAUSTED');check(e.state=='partial' and e.spent_steps==2)
test('Принудительный общий бюджет и резерв завершения',global_budget,'regression','F21')

def snapshot_good():
    e=ProcedureEngine(BASE,MIN);commit_next(e);s=e.snapshot();r=ProcedureEngine.restore(e.case,s,trusted_tail=s['events'][-1]['hash'])
    check(r.state==e.state and r.spent_steps==e.spent_steps and r.plan==e.plan)
test('Неизменный снимок восстанавливается',snapshot_good,'positive','F13')

def snapshot_tamper():
    e=ProcedureEngine(BASE,MIN);s=e.snapshot();tail=s['events'][-1]['hash'];c=deepcopy(e.case);c['sources'][0]['locator']='Замена'
    s['case_digest']=digest(c)
    must_raise(lambda:ProcedureEngine.restore(c,s,trusted_tail=tail),'закреплён')
test('Подмена снимка при прежнем доверенном журнале отвергается',snapshot_tamper,'regression','F13')

def snapshot_plan_tamper():
    e=ProcedureEngine(BASE,MIN);s=e.snapshot();tail=s['events'][-1]['hash'];s['plan'][0]['status']='pass';must_raise(lambda:ProcedureEngine.restore(e.case,s,trusted_tail=tail),'закреплён')
test('Подмена плана в контрольной записи отвергается',snapshot_plan_tamper,'negative','F13')

def untrusted_restore():
    e=ProcedureEngine(BASE,MIN);s=e.snapshot();must_raise(lambda:ProcedureEngine.restore(e.case,s));r=ProcedureEngine.restore(e.case,s,allow_untrusted=True);check(r.state=='degraded' and r.next_step()['procedure'] is None)
test('Недоверенное восстановление не разрешает исполнение',untrusted_restore,'negative','F13')

# Exact action scope. Real-like fixture is explicitly artificial and never executed.
def action_case():
    c=deepcopy(BASE);c['data_kind']='real';c['status']='active';c['contract']['intended_use']='authorized_execution'
    c['sources'][0]['kind']='file'
    for e in c['evidence']:e['mode']='direct'
    c['claims'][0]['M']['allowed_use']='recommendation';rebind(c)
    p={'id':'ACT1','version':1,'operation_id':'OP1','target_id':'synthetic_target','target_version':'7','parameters':{'value':3},
       'context_id':'CTX1','recipient':'test_only','expected_postcondition':'Искусственный пример договора','reversibility':'reversible','expires_at':'2099-01-01T00:00:00Z'}
    c['action_proposals']=[p]
    a={'id':'AUTH1','version':1,'owner':'Испытательный субъект, не реальный мандат','scope':'Синтетическая проверка локального договора',
       'operation_id':'OP1','context_id':'CTX1','verification':'externally_verified','verification_evidence_ids':['E1'],
       'valid_from':'2020-01-01T00:00:00Z','valid_until':'2099-01-01T00:00:00Z','policy_source_ids':['S1'],'verifier':'fixture',
       'proposal_digest':digest(p),'use_state':'active'}
    c['authorities']=[a]
    c['decisions']=[{'id':'DEC1','version':1,'selected_operation_id':'OP1','basis_claim_ids':['P1'],'authority_id':'AUTH1','status':'authorized',
       'context_id':'CTX1','criterion':'Искусственный договор параметров','executor':'no_external_executor','idempotency_key':'INTENT1',
       'reopen_trigger':'Любое изменение','execution_evidence_ids':[],'proposal_id':'ACT1','use_state':'active'}]
    for gate in ['G05','G08']:
        r={'id':'AR.'+gate,'version':1,'decision_id':'DEC1','proposal_id':'ACT1','proposal_digest':digest(p),'context_id':'CTX1',
           'gate':gate,'verdict':'pass','evidence_ids':['E1'],'expires_at':'2099-01-01T00:00:00Z','dependency_fingerprint':dependency_fingerprint(c,['DEC1','ACT1','E1']),
           'lifecycle':'active','supersedes_ids':[],'scope':'Искусственная проверка','allow_provisional_basis':False,'provisional_rationale':None}
        c['action_reviews'].append(r)
    return c

def boundary(c):return action_boundary(c,'DEC1',trusted_authority_bindings={'AUTH1':digest(c['authorities'][0])},now=NOW)
def action_positive():
    c=action_case();check(not codes(c),str(codes(c)));r=boundary(c);check(r['boundary_passed_under_declared_inputs'],str(r));check(not r['execution_performed'])
test('Близкий допустимый договор действия без исполнения',action_positive,'positive','F16')

def action_mutate(field,expected):
    c=action_case()
    if field=='allowed_use':c['claims'][0]['M']['allowed_use']='none';rebind(c)
    if field=='target':c['action_proposals'][0]['target_id']='other'
    if field=='parameters':c['action_proposals'][0]['parameters']['value']=300
    if field=='recipient':c['action_proposals'][0]['recipient']='other'
    if field=='expired':c['authorities'][0]['valid_until']='2020-01-01T00:00:00Z'
    if field=='denial':
        r=deepcopy(c['action_reviews'][0]);r['id']='AR.DENY';r['gate']='G08';r['verdict']='kill_fail';c['action_reviews'].append(r)
    r=boundary(c);check(not r['boundary_passed_under_declared_inputs'] and expected in r['reasons'],str(r));return r['reasons']
for field,expected in [('allowed_use','BASIS_USE_FORBIDDEN'),('target','AUTHORITY_ACTION_MISMATCH'),('parameters','AUTHORITY_ACTION_MISMATCH'),('recipient','AUTHORITY_ACTION_MISMATCH'),('expired','AUTHORITY_INVALID'),('denial','UNRESOLVED_DENIAL')]:
    test('Допуск: '+field,lambda f=field,e=expected:action_mutate(f,e),'regression','F16' if field in ('allowed_use','denial') else 'F17')

def no_trusted_bound():
    c=action_case();r=action_boundary(c,'DEC1',trusted_authority_ids=frozenset(['AUTH1']),now=NOW);check('NO_BOUND_EXTERNAL_ATTESTATION' in r['reasons'])
test('Один ID не создаёт доверенное полномочие',no_trusted_bound,'negative','F18')

def policy_impact():
    c=action_case();s=deepcopy(c['sources'][0]);s['id']='POLICY';c['sources'].append(s);c['authorities'][0]['policy_source_ids']=['POLICY'];r=dependency_impact(c,['POLICY']);check('AUTH1' in r['authorities'] and 'DEC1' in r['decisions']);return r['authorities']
test('Отзыв политики достигает Authority и Decision',policy_impact,'regression','F10')

def waiver_bad():
    c=action_case();c['authorities'][0]['verification']='unverified';c['authorities'][0]['valid_until']='2020-01-01T00:00:00Z'
    r=deepcopy(c['reviews'][0]);r.update(id='WAIVE',gate='G08',verdict='waived',target_claim_id='H1',
        waiver={'original_verdict':'hard_fail','authority_id':'AUTH1','expires_at':'2099-01-01T00:00:00Z','scope':'Искусственное исключение','policy_evidence_ids':['E1'],'compensating_claim_ids':['P1']})
    r['binding']=review_binding(c,'H1',r['evidence_ids']);c['reviews'].append(r);check('WAIVER_AUTHORITY' in codes(c))
test('Исключение не принимает просроченное непроверенное право',waiver_bad,'regression','F18')

def model_empty():
    c=deepcopy(BASE);c['models']=[{'id':'EMPTY','version':1,'kind':'factor','context_id':'CTX1','claim_ids':[],'relation_ids':[],
       'assumptions':[],'limits':[],'identification_status':'identified_within_scope','method_contract':None,'assertion_claim_id':None,'assessment_review_id':None,'use_state':'active'}]
    check('MODEL_UNGROUNDED' in codes(c))
test('Пустая модель не получает сильную метку',model_empty,'regression','F20')

# Generation + strict inference + differential comparison: actual deterministic behavior.
def cand(identifier,text,expectations,*,kind='hypothesis',op='GC-C001',risk='ordinary',frame='Объект'):
    content={'text':text,'structure':{'mechanism':text}}
    if kind=='question':content['question']=text
    return {'id':identifier,'version':1,'kind':kind,'content':content,'seed':'Изменился отчёт','operator_id':op,'axis':'механизм',
       'frame':frame,'distinguishing_features':[text],'conditions':[],'claim_ids':[],'status':'candidate','expectations':expectations,
       'scope':'Учебная очередь','parent_ids':[],'miss_risk':risk,'projections':{}}
CAND=[cand('K1','Изменилась формула измерения',{'report':'slow','raw':'same'},frame='Измеритель'),
      cand('K2','Реальное замедление процесса',{'report':'slow','raw':'slow'})]
OBS=[{'id':'O1','key':'report','value':'slow','source_id':'synthetic/log1','origin_group':'source1','state':'observed','method_valid':True,'used_for_generation':False}]
GEN={'id':'GREQ1','task':'Породить объяснения изменения отчёта','product_kind':'hypothesis','seed':'Отчёт показывает замедление','scope':'Учебная очередь',
     'frame':'Несколько моделей','constraints':[],'method':'supplied','max_candidates':10,'scan_budget':20,'supplied_candidates':CAND}
REQUEST={'generation':GEN,'candidates':CAND,'observations':OBS,'scope':'Учебная очередь','question':'Изменилось измерение или сам процесс?'}

def triad_modes():
    out={}
    for n in (1,2,3):
        for combo in combinations('GSD',n):
            r=execute_components(combo,REQUEST);check(set(r['executed_components'])==set(combo));check(set(r['outputs'])==set(combo))
            if 'D' in combo and 'S' not in combo:check(r['outputs']['D']['status']=='partial')
            if 'G' in combo:check(r['outputs']['G']['status']=='awaiting_validation')
            out[''.join(combo)]={k:v.get('status',v.get('type')) for k,v in r['outputs'].items()}
    return out
test('Все семь непустых режимов без скрытого компонента',triad_modes,'composition','F01')

def new_discriminator():
    r=execute_components('GSD',REQUEST)['outputs']['D'];check(r['compatible_in_model']==['K1','K2'] and r['discriminators'][0]['question_key']=='raw')
    req=deepcopy(REQUEST);req['observations'].append({'id':'O2','key':'raw','value':'same','source_id':'synthetic/log2','origin_group':'source2','state':'observed','method_valid':True,'used_for_generation':False})
    r2=execute_components('GSD',req)['outputs']['D'];check(r2['compatible_in_model']==['K1'] and r2['contradicted_in_model']==['K2']);check(not r2['action_authorized'])
    return {'before':r['compatible_in_model'],'after':r2['compatible_in_model']}
test('Новый различитель меняет сравнительный результат',new_discriminator,'semantic_finite_model','F26')

def duplicate_source():
    obs=deepcopy(OBS);o=deepcopy(obs[0]);o['id']='Ocopy';obs.append(o);r=StrictComponent().compare(CAND,obs,scope=REQUEST['scope'])
    check(all(len(x['support'])==1 and x['dependent']==['Ocopy'] for x in r['rows']))
test('Пересказ одного источника не умножает поддержку',duplicate_source,'semantic_finite_model','F26')

def no_measurement():
    o=deepcopy(OBS);o[0]['state']='not_measured';r=StrictComponent().compare(CAND,o,scope=REQUEST['scope']);check(all(x['status']=='underdetermined' for x in r['rows']))
test('Ненаблюдаемое оставляет версии неразличимыми',no_measurement,'semantic_finite_model','F14')

def discovery_not_confirmation():
    o=deepcopy(OBS);o[0]['used_for_generation']=True;r=StrictComponent().compare(CAND,o,scope=REQUEST['scope']);check(all(not x['support'] for x in r['rows']))
test('Данные построения не считаются независимым подтверждением',discovery_not_confirmation,'semantic_finite_model','F26')

def standalone_d():
    req=deepcopy(REQUEST);req['review']=StrictComponent().compare(CAND,OBS,scope=req['scope'])
    r=execute_components('D',req);check(r['executed_components']==['D'] and r['outputs']['D']['status']=='bounded_comparison')
    req['candidates'][0]['version']=2;must_raise(lambda:execute_components('D',req),'другой версии')
test('D отдельно принимает свежий внешний проверочный пакет',standalone_d,'composition','F01')

def questions_only():
    g=deepcopy(GEN);g['product_kind']='question';g['supplied_candidates']=[cand('Q1','Какие исходные события доступны?',{},kind='question',op='GC-I008')]
    r=GenerationComponent().run(g);check(not r['candidates'][0]['claim_ids'] and r['candidates'][0]['kind']=='question')
test('Вопрос-кандидат не становится фактом ответа',questions_only,'semantic_finite_model','F06')

def false_established():
    c=deepcopy(CAND[0]);c['status']='supported';must_raise(lambda:validate_candidate(c),'не устанавливает')
test('Генератор не повышает статус до установленного',false_established,'negative','F04')

def rename_duplicate():
    g=deepcopy(GEN);c=deepcopy(CAND[0]);c['id']='RENAMED';c['content']['text']='Иная словесная упаковка';g['supplied_candidates'].append(c)
    r=GenerationComponent().run(g);check(len(r['candidates'])==2 and len(r['selection']['not_selected'])==1)
test('Новая подпись не создаёт новую объявленную структуру',rename_duplicate,'semantic_finite_model','F26')

def morphology():
    g=deepcopy(GEN);g.update(method='morphological',product_kind='model',axes={'queue':['one','many'],'ordering':['fifo','priority']},
       forbidden_combinations=[{'queue':'one','ordering':'priority'}]);g.pop('supplied_candidates')
    r=GenerationComponent().run(g);check(len(r['candidates'])==3 and r['resource']['attempted']==4);check(len(r['applications'][0]['rejected'])==1)
test('Комбинирование уважает объявленную несовместимость',morphology,'semantic_finite_model','F04')

def bounded_morphology():
    g=deepcopy(GEN);g.update(method='morphological',product_kind='model',axes={'x':list(range(100)),'y':list(range(100))},max_candidates=3);g.pop('supplied_candidates')
    r=GenerationComponent().run(g);check(r['resource']['attempted']==3 and r['applications'][0]['unexamined_at_least']==9997)
test('Комбинаторный поиск ограничен до исчерпания произведения',bounded_morphology,'resource','F24')

def analogy_requires_boundary():
    c=deepcopy(CAND[0]);c['operator_id']='GC-D001';must_raise(lambda:validate_candidate(c),'Аналогия')
    c['content']['analogy']={'source_domain':'поток','target_domain':'очередь','mapping':{'накопление':'ожидание'},'breakpoints':['Разные законы перехода']};check(validate_candidate(c))
test('Аналогия требует отображения и точки разрыва',analogy_requires_boundary,'semantic_contract','F04')

def strict_modus_ponens():
    p=[{'id':'P','proposition':'A','source':'предъявленная посылка','status':'assumption'}]
    rules=[{'id':'R','if':'A','then':'B','source':'предъявленное правило'}]
    r=StrictComponent().derive(p,rules,scope='Формальная система');check(len(r['steps'])==1 and r['facts'][-1]['proposition']=='B')
    p[0]['proposition']='B';r2=StrictComponent().derive(p,rules,scope='Формальная система');check(not r2['steps'])
    return {'valid_derivation':r['steps'][0]['rule'],'affirming_consequent_rejected':True}
test('S выполняет вывод, но не утверждение основания по следствию',strict_modus_ponens,'semantic_finite_model','F01')

def ga_missing():
    g=deepcopy(GEN);g['adversarial']=True;g['ga_results']=[];must_raise(lambda:GenerationComponent().run(g),'каждого GA')
test('Общая отметка GA не закрывает двенадцать приёмов',ga_missing,'negative','F04')

for ga_num in range(1,13):
    def ga_case(ga_num=ga_num):
        g=deepcopy(GEN);op=f'GA-{ga_num:02d}';c=deepcopy(CAND[0]);c['operator_id']=op;c['id']='GAOUTPUT'
        if ga_num in (8,9):c['content']['analogy']={'source_domain':'предмет S','target_domain':'предмет T','mapping':{'a':'b'},'breakpoints':['непереносимый закон']}
        g['supplied_candidates']=[c];g['adversarial']=True
        g['ga_results']=[{'operator_id':f'GA-{i:02d}','applicability':'applied' if i==ga_num else 'not_applicable',
                           'reason':'Искусственная проверка индивидуального договора, не оценка всех смыслов GA', 'candidate_ids':['GAOUTPUT'] if i==ga_num else []} for i in range(1,13)]
        r=GenerationComponent().run(g);check(len(r['ga_results'])==12)
        g['ga_results'][ga_num-1]['candidate_ids']=[];must_raise(lambda:GenerationComponent().run(g),'без индивидуального выхода')
    test(f'GA-{ga_num:02d}: индивидуальное исполнение и отрицательный случай',ga_case,'semantic_contract','F04')

# Corpus and context closure.
def source_routes():
    c=Corpus()
    for op in ['GA-02','GA-04','GA-10','GC-A001','GC-E002']:
        rows=c.lookup('generative',op);check(rows and all(r['route']=='G.SOURCE.'+op for r in rows))
    for family in ['GG01','GP01','GS01','GM1','GQ1']:
        check(c.lookup('generative',family))
    return {'exact_source_routes_checked':5,'previously_unaddressed_families':5}
test('Маршруты по точной операции, не словам решения',source_routes,'corpus','F02')

def raw_input():
    r=intake_raw('Проверить утверждение с отсутствующим J');check(r['state']=='draft' and not r['action_authorized']);check(r['missing_fields'])
test('Сырой вход принимается до ValidatedCase',raw_input,'positive','F07')

def shared_budget():
    b=SharedBudget(4,1);check(b.allocate('G',2));must_raise(lambda:b.allocate('S',2));b.settle('G',2);check(b.allocate('S',1));b.settle('S',1);check(b.spent==3);check(not b.allocate('G',2))
test('Передача и повтор не обнуляют общий ресурс',shared_budget,'resource','F21')

# Additional cross-boundary regressions; all inputs are artificial.
def planned_results():
    c=deepcopy(BASE);t=audit_test_plan(c);check(not codes(c),str(codes(c)));t['result_evidence_ids']=['E1'];check('TEST_UNRUN_RESULT' in codes(c))
    t['status']='completed';check(not codes(c),str(codes(c)))
    t['result_evidence_ids']=[];check('TEST_UNUSABLE' in codes(c))
test('План, результат и пустой завершённый тест различаются',planned_results,'regression','F14')

def receipt_injection():
    e=ProcedureEngine(BASE,MIN);commit_next(e);c=deepcopy(e.case);c['revision']+=1;r=deepcopy(c['procedure_runs'][0]);r['id']='FORGED';c['procedure_runs'].append(r)
    must_raise(lambda:e.update_case(c,expected_revision=e.case['revision']),'только commit')
test('Агент не импортирует собственную запись как исполнение контроллера',receipt_injection,'regression','F19')

def actual_application():
    e=ProcedureEngine(BASE,MIN)
    while True:
        p=e.next_step()['procedure'];check(p is not None);commit_next(e)
        if p['id']=='ATOM.03':break
    run=next(x for x in e.case['procedure_runs'] if x['procedure_id']=='ATOM.03')
    src=Corpus().lookup('strict','C-A002')[0]
    ap={'id':'APREAL','version':1,'source_element_key':src['key'],'source_hash':src['source_sha256'],'exact_text':src['exact_text'],
        'target_claim_ids':run['target_claim_ids'],'procedure_id':'ATOM.03','role':'distinction','local_obligation':'Разделение наблюдения и приписанной интерпретации в искусственных тезисах',
        'input_refs':run['input_refs'],'expected_output':'Самостоятельная карточка каждого тезиса','counterexample':'Интерпретация записана наблюдением',
        'status':'applied','result_artifact_ids':run['output_ids'],'reason':'Проверяется адресность исполнения; содержание имитирует испытатель',
        'run_id':run['id'],'target_versions':{c['id']:c['version'] for c in e.case['claims']}}
    c=deepcopy(e.case);c['revision']+=1;c['source_applications'].append(ap);check(not codes(c),str(codes(c)));e.update_case(c,expected_revision=e.case['revision'])
    check(e.case['source_applications'][0]['status']=='applied')
    snap=e.snapshot();rest=ProcedureEngine.restore(e.case,snap,trusted_tail=snap['events'][-1]['hash']);check(rest.case['source_applications']==e.case['source_applications'])
    wrong=deepcopy(e.case);wrong['source_applications'][0]['target_claim_ids']=['H1'];check('APPLICATION_TARGET' in codes(wrong))
    wrong=deepcopy(e.case);wrong['source_applications'][0]['run_id']=None;check('APPLICATION_NO_RUN' in codes(wrong))
    must_raise(lambda:ProcedureEngine(e.case,MIN),'Импортированная')
    return {'actual_receipt_id':run['id'],'targets':len(run['target_claim_ids'])}
test('applied связан с действительным запуском, целью и результатом',actual_application,'regression','F19')

def source_sections_exact():
    from corpus import FILES
    data=load_json(ROOT/'data/source_sections.json')
    for sid in ['strict','generative','delivery']:
        text=''.join(x['text'] for x in data['sections'] if x['source']==sid)
        check(text.encode('utf-8')==(ROOT/'sources'/FILES[sid]).read_bytes(),sid)
    corpus=Corpus()
    for row in corpus.entries.values():
        x=corpus.exact(row['key']);check(x['definition'].rstrip('\r\n')==row['exact_text'].rstrip('\r\n'),row['key'])
    return {'named_entries':len(Corpus().entries),'full_sections':data['section_count']}
test('Все исходные разделы и адресованные определения сохраняют текст',source_sections_exact,'corpus','F03')

def manifest_fixture():
    c=Corpus();m=c.manifest(components='G',entry_keys=['generative:GC-A001'])
    loaded_files={x['path']:x['sha256'] for x in m['files']};loaded_entries={x['key']:(x['definition_sha256'],x['parent_sha256']) for x in m['entries']}
    return c,m,loaded_files,loaded_entries

def manifest_good():
    c,m,f,e=manifest_fixture();check(c.verify_manifest(m,loaded_files=f,loaded_entries=e));return len(f)
test('Самостоятельный G загружает общее ядро, свой договор и точный источник',manifest_good,'positive','F23')
for mutation in ('missing_file','missing_parent','changed_digest','wrong_component'):
    def manifest_bad(mutation=mutation):
        c,m,f,e=manifest_fixture()
        if mutation=='missing_file':f.pop(next(iter(f)))
        elif mutation=='missing_parent':k=next(iter(e));e[k]=(e[k][0],'0'*64)
        elif mutation=='changed_digest':m['digest']='0'*64
        else:
            must_raise(lambda:c.manifest(components='G',entry_keys=['strict:C-A002']),'Скрытая');return
        must_raise(lambda:c.verify_manifest(m,loaded_files=f,loaded_entries=e))
    test('Замыкание контекста отклоняет '+mutation,manifest_bad,'negative','F23')

def handoff_fixture():
    b=SharedBudget(20,1);objects={'K1':deepcopy(CAND[0]),'context':{'id':'CTX','version':1,'scope':'учебное'},'standard':{'id':'STD','version':1,'required':'кандидат'}}
    versions={'G':'3.0','S':'3.0','D':'3.0'};cor=digest(Corpus().registry['sources'])
    m={'id':'MSG1','sender':'G','receiver':'S','protocol_version':'3.0','component_versions':versions,'corpus_digest':cor,
       'payload_id':'K1','payload_version':1,'payload_digest':digest(objects['K1']),'dependency_bindings':{'K1':digest(objects['K1'])},
       'context_digest':digest(objects['context']),'standard_digest':digest(objects['standard']),'risk_floor':'Standard',
       'deadline':'2099-01-01T00:00:00Z','budget_reservation':'RES1','budget_amount':2,'allowed_effects':['local_analysis'],
       'residuals':residuals(),'input_status':'candidate'}
    return HandoffChannel(component_versions=versions,corpus_digest=cor,budget=b,risk_floor='Standard'),m,objects,b

def handoff_replay():
    ch,m,o,b=handoff_fixture();r=ch.send(m,objects=o,receiver='S',now=NOW);r2=ch.send(m,objects=o,receiver='S',now=NOW)
    check(not r['duplicate'] and r2['duplicate'] and not r2['epistemic_promotion'] and len(b.reservations)==1)
    m['deadline']='2020-01-01T00:00:00Z';must_raise(lambda:ch.send(m,objects=o,receiver='S',now=NOW),'Поздний')
test('Передача повторяется без нового расхода, но проверяет срок до повтора',handoff_replay,'composition','F17')
for mutation in ('payload','dependency','context','standard','risk','protocol','residual','effects','reservation'):
    def handoff_bad(mutation=mutation):
        ch,m,o,b=handoff_fixture()
        if mutation=='payload':o['K1']['version']=2
        elif mutation=='dependency':m['dependency_bindings']['missing']='0'*64
        elif mutation=='context':o['context']['scope']='другая среда'
        elif mutation=='standard':o['standard']['required']='иной стандарт'
        elif mutation=='risk':m['risk_floor']='eMVP'
        elif mutation=='protocol':m['protocol_version']='2.0'
        elif mutation=='residual':m['residuals'].pop('unknown')
        elif mutation=='effects':m['allowed_effects']=['execute_external']
        else:ch.send(m,objects=o,receiver='S',now=NOW);m['id']='MSG2'
        must_raise(lambda:ch.send(m,objects=o,receiver='S',now=NOW))
    test('Граница передачи отклоняет '+mutation,handoff_bad,'negative','F04')

def principle_fixture():
    return {'id':'PC1','statement':'Из наличия отчёта не следует подтверждённость содержимого',
        'primary_C_ID':'C-D002','D_path':['D1'],'D_required_reason':'Исследование источника','M_path':['M1'],'M_required_reason':'Критическая проверка перехода',
        'E_ID':'E001','Q_ID':'Q1','register_profile':{k:'Явная область '+k for k in 'OEAD'},'S0_pass_reason':'Проверяется форма одного различения',
        'H_role':'none','H_not_used_for_validation':True,'negative_grammar_hits':[]}
def principle_good():
    r=StrictComponent().principle_contract(principle_fixture());check(r['status']=='well_formed_candidate');return r['semantic_forward_derivability']
test('Специальная грамматика строгого принципа отделена от обычного факта',principle_good,'semantic_contract','F03')
for mutation in ('missing_C','missing_D','missing_M','wrong_E','hook_validates','negative_hit'):
    def principle_bad(mutation=mutation):
        p=principle_fixture()
        if mutation=='missing_C':p['primary_C_ID']='P001'
        elif mutation=='missing_D':p['D_path']=[]
        elif mutation=='missing_M':p['M_path']=[]
        elif mutation=='wrong_E':p['E_ID']='E999'
        elif mutation=='hook_validates':p['H_not_used_for_validation']=False
        else:p['negative_grammar_hits']=['NG1']
        must_raise(lambda:StrictComponent().principle_contract(p))
    test('Грамматика принципа отклоняет '+mutation,principle_bad,'negative','F03')

def limited_not_automatic():
    e=ProcedureEngine(BASE,MIN);n=e.next_step();p=n['procedure'];a=artifact(e,p);c=deepcopy(e.case);c['revision']+=1;c['artifacts'].append(a);e.update_case(c,expected_revision=e.case['revision'])
    e.commit(p['id'],'LIMITED1','limited',[a['id']],expected_revision=e.case['revision'],postcondition_observed='Ограниченный учебный результат',reason='Нет достаточности для произвольного применения')
    check(not e._accepted(p['id'],'CLOSURE'));must_raise(lambda:e.accept_limited(p['id'],'CLOSURE',review_id='MISSING',reason='запрошено'))
    rid=next(r['id'] for r in e.case['reviews'] if r['target_claim_id']=='P1' and r['verdict']=='pass')
    e.accept_limited(p['id'],'SPECIFIC_CONSUMER',review_id=rid,reason='Учебная приемка только определённого входа')
    check(e._accepted(p['id'],'SPECIFIC_CONSUMER') and not e._accepted(p['id'],'CLOSURE'))
test('Ограниченный результат принимается только указанным потребителем',limited_not_automatic,'regression','F22')

def duplicate_session_budget():
    b=SharedBudget(100,1);execute_components('GSD',REQUEST,budget=b);spent=b.spent
    must_raise(lambda:execute_components('GSD',REQUEST,budget=b),'уже учтён');check(b.spent==spent)
test('Повтор запуска не начинает вычисление без нового резерва',duplicate_session_budget,'resource','F21')

# Persist actual finite-model examples generated during this test run.
(ROOT/'examples/triad_request.json').write_text(json.dumps(REQUEST,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for mode in ('G','S','D','GS','GD','SD','GSD'):
    result=execute_components(mode,REQUEST)
    (ROOT/'examples'/('result_'+mode+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


# Final interface/state adversarial checks.
def real_context_assembly():
    c,m,_,_=manifest_fixture();assembled=c.assemble_context(m,byte_limit=2_000_000)
    check('GC-A001' in assembled['text'] and assembled['bytes']>0)
    must_raise(lambda:c.assemble_context(m,byte_limit=20),'не помещается')
    required=set(c.closure['mandatory_sections']['G']);check(required<={x['key'] for x in m['entries']})
    return {'delivered_bytes':assembled['bytes'],'mandatory_source_sections':len(required)}
test('Фактическая сборка включает ядро и отвергает скрытую обрезку',real_context_assembly,'integration','F23')

def retained_archive():
    g=deepcopy(GEN);c=deepcopy(CAND[0]);c['id']='RENAMED';c['content']['text']='Другое имя';g['supplied_candidates'].append(c)
    out=GenerationComponent().run(g);check(len(out['archived_candidates'])==1 and out['archived_candidates'][0]['id']=='RENAMED')
    g=deepcopy(GEN);g['known_candidates']=[deepcopy(CAND[0])];out=GenerationComponent().run(g)
    check(len(out['candidates'])==1 and out['archived_candidates'][0]['id']=='K1')
test('Группировка сохраняет полное содержание и прежнюю новизну',retained_archive,'semantic_contract','F04')

for non_operator in ['GQ1','GM1','GS01','GG01','GC-A008']:
    def no_substitution(non_operator=non_operator):
        c=deepcopy(CAND[0]);c['operator_id']=non_operator;must_raise(lambda:validate_candidate(c),'не подменяет')
    test('Тип '+non_operator+' не заменяет порождающую операцию',no_substitution,'negative','F03')

def handoff_status():
    ch,m,o,b=handoff_fixture();m['input_status']='supported';must_raise(lambda:ch.send(m,objects=o,receiver='S',now=NOW),'эпистемический статус')
test('Сообщение не повышает статус кандидата полем заголовка',handoff_status,'negative','F04')

def standalone_formal():
    req=load_json(ROOT/'examples/strict_derivation.json');r=execute_components('S',req)
    check(r['executed_components']==['S'] and r['outputs']['S']['type']=='FormalDerivation')
    (ROOT/'examples/result_S_derivation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    p=deepcopy(req['premises']);p.append({'id':'P1','proposition':'Z','source':'иной материал','status':'given'})
    must_raise(lambda:StrictComponent().derive(p,req['implications'],scope=req['scope']),'уникальной')
test('Самостоятельный S выводит следствие без DDx и защищает идентичность посылок',standalone_formal,'composition','F01')

def limited_revoke():
    e=ProcedureEngine(BASE,MIN);n=e.next_step();p=n['procedure'];a=artifact(e,p)
    c=deepcopy(e.case);c['revision']+=1;c['artifacts'].append(a);review=deepcopy(c['reviews'][0]);review['id']='LIMITREVIEW';c['reviews'].append(review);e.update_case(c,expected_revision=e.case['revision'])
    e.commit(p['id'],'LIMITBIND','limited',[a['id']],expected_revision=e.case['revision'],postcondition_observed='Учебное ограничение',reason='Только объявленный потребитель')
    e.accept_limited(p['id'],'CONSUMER',review_id='LIMITREVIEW',reason='Адресная учебная приемка')
    check(e._accepted(p['id'],'CONSUMER'))
    c=deepcopy(e.case);c['revision']+=1;r=next(r for r in c['reviews'] if r['id']=='LIMITREVIEW');r['version']+=1;r['lifecycle']='stale';e.update_case(c,expected_revision=e.case['revision'])
    check(not e._accepted(p['id'],'CONSUMER'))
test('Отзыв приемки ограниченного входа блокирует его прежнего потребителя',limited_revoke,'regression','F22')



def generative_status_trace():
    r=GenerationComponent().run(GEN);run=r['generation_run']
    check(len(run['phase_records'])==10 and len(run['protocol_records'])==5)
    check(next(x for x in run['phase_records'] if x['source_status_id']=='GS09')['state']=='not_performed_by_generator')
    check(next(x for x in run['phase_records'] if x['source_status_id']=='GS08')['state']=='prepared_not_delivered')
    check(all(a['status']=='candidate_received_not_generated_here' for a in r['applications']))
test('GS/GP различают получение, порождение, передачу и внешнюю валидацию',generative_status_trace,'semantic_contract','F04')



def typed_value_comparison():
    c=deepcopy(CAND[0]);c['expectations']={'reading':1}
    o=deepcopy(OBS[0]);o['key']='reading';o['value']=True
    r=StrictComponent().compare([c],[o],scope=c['scope']);check(r['rows'][0]['status']=='contradicted_prediction')
    o['value']=1;r=StrictComponent().compare([c],[o],scope=c['scope']);check(r['rows'][0]['status']=='compatible_prediction')
test('S не отождествляет логическое true и числовую единицу',typed_value_comparison,'semantic_finite_model','F14')

def scope_requires_transport():
    must_raise(lambda:StrictComponent().compare(CAND,OBS,scope='Другой объект и популяция'),'другой C')
test('S запрещает необъявленный перенос в чужой контекст',scope_requires_transport,'negative','F15')


# Full detailed plan traces: structural fixtures, explicitly NOT agent behavior tests.
TRACE=[]
for profile in ([] if '--skip-traces' in sys.argv else [sys.argv[sys.argv.index('--trace-profile')+1]] if '--trace-profile' in sys.argv else PROFILES):
    def trace(profile=profile):
        c=deepcopy(BASE);c['requested_profile']=profile;e=ProcedureEngine(c,MIN);n=finish(e);e.close(criterion_record='Искусственная приемка договора очереди, не пригодности агента')
        s=e.snapshot();r=ProcedureEngine.restore(e.case,s,trusted_tail=s['events'][-1]['hash']);check(r.state=='closed')
        row={'profile':profile,'procedures':n,'steps_spent':r.spent_steps,'semantic_agent_validation':False};TRACE.append(row);return row
    test('Подробный цикл и восстановление: '+profile,trace,'synthetic_controller_trace','F08')

report={'version':'3.0','date':'2026-09-12','test_count':len(RESULTS),'passed_count':sum(r['passed'] for r in RESULTS),
        'failed_count':sum(not r['passed'] for r in RESULTS),'profile_property_combinations':0 if '--trace-profile' in sys.argv else 192,'traces':TRACE,
        'scope':'Программные договоры, конечные смысловые примеры и композиция. Нет испытаний свободного поведения LLM, клинической или промышленной пригодности.',
        'environment':{'python':sys.version,'platform':platform.platform()},'tests':RESULTS}
report_name='trace_'+sys.argv[sys.argv.index('--trace-profile')+1].replace(' ','_')+'.json' if '--trace-profile' in sys.argv else 'core_verification_report.json' if '--skip-traces' in sys.argv else 'verification_report.json'
(ROOT/'reports'/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('tests','environment','traces')},ensure_ascii=False,indent=2))
for r in RESULTS:
    if not r['passed']:print('FAIL',r['name'],r['error'])
if report['failed_count']:raise SystemExit(1)
