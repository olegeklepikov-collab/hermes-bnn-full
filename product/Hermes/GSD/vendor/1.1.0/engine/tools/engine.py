"""GSD 3.0: контроллер подробного диагностического цикла и совместимый CLI.
Смысловые операции выполняет агент, программа контролирует адресные договоры.
Три самостоятельных интерфейса и их композиция находятся в triad.py.
"""
from __future__ import annotations
import argparse, json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Iterable
from records import *
TERMINAL=frozenset(('pass','limited','not_applicable'))
STOPPED=frozenset(('partial','blocked','closed','degraded'))

def normalized_content(x):
    """Номер редакции не является новым содержательным входом."""
    if isinstance(x,dict):return {k:normalized_content(v) for k,v in x.items() if k not in ('revision','version')}
    if isinstance(x,list):return [normalized_content(v) for v in x]
    return x

def effective_triggers(case,triggers,catalog):
    needed={p['activation_trigger'] for p in catalog.values() if p['activation_trigger']}
    if set(triggers)!=needed or any(v is not None and type(v) is not bool for v in triggers.values()):
        raise ValueError('Требуется точный набор типизированных триггеров: '+','.join(sorted(needed)))
    flags=dict(triggers);rank=PROFILES.index(choose_profile(case['requested_profile'],case['risk'])['selected'])
    facts={
      'action_requested':case['contract']['intended_use']!='analysis_only' or bool(case['decisions']),
      'prior_action':any(d['status'] in ('sent','executed','outcome_unknown') for d in case['decisions']),
      'high_stakes':rank>=4,
      'multilevel':bool(case['relations']) or any(m['kind']=='factor' for m in case['models']),
      'complex_model':bool(case['models']), 'history_material':bool(case['genesis']),
      'test_needed':bool(case['tests']), 'source_application':bool(case['source_applications']),
      'comparison_material':len(case['claims'])>1,
      'claim_type_material':any(c['P']['kind'] in ('causal','forecast','normative','recommendation','probabilistic') for c in case['claims']),
    }
    for k,v in facts.items():
        if k in flags and v:flags[k]=True
    return flags

def claim_bindings(case,procedure):
    if procedure.get('execution_scope')!='each_claim':return []
    result=[]
    for c in case['claims']:
        if c['M']['epistemic_status']=='superseded':continue
        result.append({'work_id':f"{procedure['id']}@{c['id']}@{c['version']}", 'claim_id':c['id'],
          'claim_version':c['version'],'claim_digest':digest(c),
          'dependency_fingerprint':dependency_fingerprint(case,[c['id']])})
    return result

class ProcedureEngine:
    """Однопроцессный контроллер; внешние эффекты и доступ защищает реальная среда."""
    def __init__(self,case:Mapping[str,Any],triggers:Mapping[str,bool|None],*,max_attempts:int=3,
                 components:Iterable[str]=('G','S','D')):
        if type(max_attempts) is not int or max_attempts<1:raise ValueError('Неверный предел попыток')
        issues=validate_case(case)
        if issues:raise ValueError('Некорректный ValidatedCase: '+','.join(i.code for i in issues))
        if any(a['status']=='applied' for a in case['source_applications']):raise ValueError('Импортированная отметка applied не является исполнением текущего запуска; используйте проверенное восстановление или миграцию')
        self.case=deepcopy(case);self.catalog_data=load_json(ROOT/'data/procedures.json')
        self.catalog={p['id']:p for p in self.catalog_data['procedures']}
        self.components=sorted(set(components))
        if not self.components or not set(self.components)<=set('GSD'):raise ValueError('Неизвестный компонент')
        self.triggers=dict(triggers);self.max_attempts=max_attempts;self.events=[];self.revision=0
        self._attempts={};self._attempt_counts={};self._success={};self._last_failure={}
        self.accepted_limits={};self.spent_steps=0;self.spent_cost=0.0;self.history=[]
        self._fp_cache={};self._bindings_cache={}
        self.state='blocked' if case['status']=='blocked' else 'partial' if case['status']=='partial' else 'active'
        self.plan=[];self.scoped_out=[];self._rebuild()
        self._event({'event':'initialized','catalog_digest':digest(self.catalog_data),'case_digest':digest(self.case),
                     'max_attempts':max_attempts,'components':self.components})

    def _event(self,payload):
        body={'sequence':len(self.events),'previous_hash':self.events[-1]['hash'] if self.events else None,'payload':deepcopy(payload)}
        body['hash']=digest(body);self.events.append(body);self.revision+=1

    def _set_state(self,value):
        self.state=value;self.case['status']=value

    def _roots(self,p):
        return [x['id'] for g in p['read_set'] for x in self.case.get(g,[])]

    def _fingerprint(self,p):
        if p['id'] in self._fp_cache:return self._fp_cache[p['id']]
        result=digest({'inputs':dependency_snapshot(self.case,self._roots(p)),
                       'contract':self.case['contract'],
                       'risk':self.case['risk'] if p['component'] in ('BOOT','CONTRACT','ASSURANCE','DECISION') else None})
        self._fp_cache[p['id']]=result
        return result

    def _bindings(self,p):
        if p['id'] not in self._bindings_cache:self._bindings_cache[p['id']]=claim_bindings(self.case,p)
        return self._bindings_cache[p['id']]

    def _current_success(self,pid):
        records=self._success.get(pid,[])
        p=self.catalog[pid]
        if p.get('execution_scope')=='each_claim':
            expected=self._bindings(p)
            if not expected:return None
            valid={b['claim_id']:(rec,b) for rec in records for b in rec.get('target_bindings',[]) if
                   rec['status'] in TERMINAL}
            if all(x['claim_id'] in valid and valid[x['claim_id']][1]==x for x in expected):
                return 'limited' if any(valid[x['claim_id']][0]['status']=='limited' for x in expected) else 'pass'
            return None
        for rec in reversed(records):
            if rec['input_fingerprint']==self._fingerprint(p):return rec['status']
        return None

    def _rebuild(self):
        rank=PROFILES.index(choose_profile(self.case['requested_profile'],self.case['risk'])['selected'])
        flags=effective_triggers(self.case,self.triggers,self.catalog)
        old={x['procedure_id']:x for x in self.plan};plan=[];scoped=[]
        for p in self.catalog.values():
            flag=flags.get(p['activation_trigger']) if p['activation_trigger'] else True
            enabled=p['mandatory_core'] or rank>=p['minimum_profile_rank'] or flag is not False
            if p['component'] in ('DECISION','MONITOR','LIFECYCLE') and flag is False and not p['mandatory_core']:enabled=False
            if not enabled:
                scoped.append({'procedure_id':p['id'],'reason':'Не активировано по явному профилю и признаку; это не исполнение'});continue
            status=self._current_success(p['id'])
            prior=old.get(p['id'],{})
            if not status:status=prior.get('status','pending') if prior.get('status') not in TERMINAL else 'pending'
            plan.append({'procedure_id':p['id'],'status':status,'attempts':self._attempt_counts.get(p['id'],0),'reason':prior.get('reason','')})
        self.plan=plan;self.scoped_out=scoped
        if self.state not in STOPPED:
            if all(x['status'] in TERMINAL for x in plan):self._set_state('ready_for_review')
            else:self._set_state('active')

    def _accepted(self,pid,consumer):
        x=next((x for x in self.plan if x['procedure_id']==pid),None)
        if x is None:return True  # Exactly the recorded inactive branch, not silent omission.
        if x['status'] in ('pass','not_applicable'):return True
        if x['status']=='limited':
            record=self.accepted_limits.get(pid+'->'+consumer)
            review=next((r for r in self.case['reviews'] if record and r['id']==record['review_id']),None)
            return bool(record and review and review['verdict']=='pass' and review['execution_state']=='completed' and review_current(self.case,review) and record['input_fingerprint']==self._fingerprint(self.catalog[pid]))
        return False

    def next_step(self):
        if self.state in STOPPED:return {'state':self.state,'procedure':None}
        # Recompute, so no stale plan can authorize closure after risk/data change.
        self._rebuild();waiting=[]
        for item in self.plan:
            if item['status'] in TERMINAL:continue
            p=self.catalog[item['procedure_id']]
            deps=[dep for dep in p['dependencies'] if not self._accepted(dep,p['id'])]
            if deps:waiting.append({'procedure_id':p['id'],'dependencies':deps});continue
            if p['owning_component'] not in self.components:
                waiting.append({'procedure_id':p['id'],'missing_component':p['owning_component']});continue
            missing=[s['collection'] for s in p['input_selectors'] if len(self.case.get(s['collection'],[]))<s['minimum']]
            return {'state':self.state,'procedure':deepcopy(p),'attempts':item['attempts'],
                    'required_input_revision':self.case['revision'],'failure_route':p['failure_action']['route'],
                    'target_bindings':self._bindings(p),'input_fingerprint':self._fingerprint(p),'missing_inputs':missing}
        return {'state':'ready_for_review' if all(x['status'] in TERMINAL for x in self.plan) else 'awaiting_evidence','procedure':None,'waiting':waiting}

    def update_case(self,new_case:Mapping[str,Any],*,expected_revision:int,revalidation:bool=False):
        if self.state=='closed':raise ValueError('Закрытый запуск требует явного reopen')
        if expected_revision!=self.case['revision'] or new_case.get('revision')!=expected_revision+1:raise ValueError('Конфликт ревизии')
        if new_case.get('case_id')!=self.case['case_id']:raise ValueError('Другой случай')
        proposed=deepcopy(new_case)
        if proposed.get('procedure_runs')!=self.case['procedure_runs']:raise ValueError('Запись исполнения создаётся только commit, не импортом результата агента')
        for ap in proposed.get('source_applications',[]):
            if ap['status']=='applied':
                rec=self._attempts.get(ap.get('run_id'))
                if not rec or rec['status'] not in ('pass','limited') or rec['procedure_id']!=ap['procedure_id'] or set(rec['output_ids'])!=set(ap['result_artifact_ids']):
                    raise ValueError('applied требует фактического результата текущего запуска')
        oldnodes,oldgroups=indexes(self.case);newnodes,newgroups=indexes(proposed)
        if set(oldnodes)-set(newnodes):raise ValueError('Нельзя молча удалять историю; используйте отзыв/санкционированную миграцию хранения')
        changed=[]
        for key in set(oldnodes)&set(newnodes):
            old=oldnodes[key];new=newnodes[key]
            if digest(old)==digest(new):continue
            ov=old.get('version');nv=new.get('version')
            if (isinstance(ov,int) and (not isinstance(nv,int) or nv<=ov)) or (not isinstance(ov,int) and nv==ov):
                raise ValueError('Изменённый объект требует новой версии: '+key)
            if digest(normalized_content(old))!=digest(normalized_content(new)):changed.append(key)
        # Versions alone do not constitute new evidence for retry.
        if revalidation and any(oldgroups[k] in ('sources','evidence','contexts') for k in changed):
            raise ValueError('Приёмка пересмотра не изменяет одновременно первичный материал или стандарт')
        oldrank=PROFILES.index(choose_profile(self.case['requested_profile'],self.case['risk'])['selected'])
        newrank=PROFILES.index(choose_profile(proposed['requested_profile'],proposed['risk'])['selected'])
        if newrank<oldrank:raise ValueError('Снижение требуемого профиля — отдельное изменение контракта, не обычное обновление')
        material=[k for k in changed if oldgroups[k] not in ('artifacts','procedure_runs','source_applications','reviews','action_reviews')]
        affected=set()
        if material and not revalidation:
            for graph in (self.case,proposed):
                affected.update(k for vals in dependency_impact(graph,material).values() for k in vals)
            for c in proposed['claims']:
                if c['id'] not in affected:continue
                if c['M']['epistemic_status'] in ('supported','refuted'):
                    c['M']['epistemic_status']='unassessed';c['M']['allowed_use']='discovery'
                    c['T']['verification']['status']='stale'
                    for dim in ('V','A','R'):
                        c['J'][dim]['state']='unknown';c['J'][dim]['limitations'].append('Изменено необходимое основание; требуется новая проверка')
                    if c['M']['probability'] is not None:c['M']['probability']=None;c['M']['modality']='possible'
                    c['version']+=1
            for group in ('reviews','action_reviews'):
                for r in proposed[group]:
                    if r['id'] in affected and r['lifecycle']=='active':r['lifecycle']='stale';r['version']+=1
            for group in ('models','tests','authorities','decisions'):
                for x in proposed[group]:
                    if x['id'] in affected:
                        x['use_state']='requires_review';x['version']+=1
                        if group=='authorities':x['verification']='unverified'
            for ap in proposed['source_applications']:
                if ap['id'] in affected and ap['status']=='applied':ap['status']='deferred';ap['version']+=1;ap['reason']='Основание изменено; прежнее исполнение сохранено исторически'
        if proposed['status']=='closed':raise ValueError('Используйте close с проверкой актуального плана')
        issues=validate_case(proposed)
        if issues:raise ValueError('Некорректное обновление: '+','.join(i.code for i in issues))
        relevant_change=any(newgroups[k] not in ('artifacts','procedure_runs') for k in changed+list(set(newnodes)-set(oldnodes))) or proposed['contract']!=self.case['contract'] or proposed['risk']!=self.case['risk']
        if relevant_change:self._fp_cache.clear();self._bindings_cache.clear()
        if relevant_change:self.history.append(deepcopy(self.case))
        self.case=proposed
        if self.case['status']=='blocked':self._set_state('blocked')
        elif self.state in STOPPED:self.case['status']=self.state  # Changes never silently resume a stopped run.
        self._rebuild()
        self._event({'event':'case_updated','case_digest':digest(self.case),'revision':self.case['revision'],'changed_ids':changed,'affected_ids':sorted(affected),'revalidation':revalidation})

    def commit(self,procedure_id,attempt_id,status,output_ids,*,expected_revision,postcondition_observed,reason='',cost=0.0):
        if expected_revision!=self.case['revision']:raise ValueError('Устаревшие входы')
        p=self.catalog.get(procedure_id)
        if not p:raise ValueError('Неизвестная процедура')
        fp=self._fingerprint(p)
        payload={'procedure_id':procedure_id,'attempt_id':attempt_id,'status':status,'output_ids':output_ids,
          'input_revision':expected_revision,'input_fingerprint':fp,'postcondition_observed':postcondition_observed,'reason':reason,'cost':cost}
        if attempt_id in self._attempts:
            if digest(self._attempts[attempt_id])!=digest(payload):raise ValueError('Конфликт идентификатора попытки или устаревание входов')
            return {'duplicate':True,'state':self.state}
        nxt=self.next_step()
        if nxt['procedure'] is None or nxt['procedure']['id']!=procedure_id:raise ValueError('Нарушены зависимости, компонент отсутствует или запуск остановлен')
        if nxt['missing_inputs'] and status in TERMINAL:raise ValueError('Недостаёт конкретного входа '+','.join(nxt['missing_inputs']))
        if status not in TERMINAL|{'needs_data','needs_repair','blocked'}:raise ValueError('Неверный исход')
        if not attempt_id.strip() or not postcondition_observed.strip():raise ValueError('Пустая запись исполнения')
        if type(cost) not in (int,float) or cost<0 or cost!=cost or cost==float('inf'):raise ValueError('Неверный расход')
        b=self.case['contract']['budget']
        if self.spent_steps+1>b['step_limit']-b['reserve_steps'] or self.spent_cost+cost>b['cost_limit'] or datetime.now(timezone.utc)>=time_value(b['deadline']):
            self.stop('Исчерпан общий исполнительный бюджет');raise ValueError('BUDGET_EXHAUSTED')
        if self._attempt_counts.get(procedure_id,0)>=self.max_attempts:raise ValueError('Исчерпан общий предел попыток процедуры')
        if self._last_failure.get(procedure_id)==fp:raise ValueError('Повтор без нового содержательного входа')
        nodes,groups=indexes(self.case);arts={x['id']:x for x in self.case['artifacts']}
        bindings=self._bindings(p)
        if status in ('pass','limited'):
            if not output_ids or len(set(output_ids))!=len(output_ids) or any(i not in arts or arts[i]['kind']!=p['output_type'] for i in output_ids):raise ValueError('Нет адресного результата нужного типа')
            for oid in output_ids:
                a=arts[oid]
                if a['input_fingerprint']!=fp:raise ValueError('Выход относится к иному набору входов')
                if not a['semantic_result_refs'] and p['component'] not in ('BOOT','CONTRACT','LIFECYCLE'):raise ValueError('Текстовая оболочка без предметного результата')
            if p.get('execution_scope')=='each_claim':
                if not bindings:raise ValueError('Нет целевого тезиса')
                if len(output_ids)!=len(bindings):raise ValueError('Нужен отдельный выход на каждый тезис')
                for bind in bindings:
                    hits=[arts[o] for o in output_ids if arts[o]['claim_ids']==[bind['claim_id']]]
                    if len(hits)!=1 or hits[0]['target_version']!=bind['claim_version'] or hits[0]['target_digest']!=bind['claim_digest'] or bind['claim_id'] not in hits[0]['semantic_result_refs']:raise ValueError('Подменена цель или версия атомарной процедуры')
            if status=='limited' and (not reason.strip() or any(not arts[o]['limitations'] for o in output_ids)):raise ValueError('Ограниченный результат требует предметного ограничения каждого выхода')
            run={'id':attempt_id,'version':1,'procedure_id':procedure_id,'target_claim_ids':[c['claim_id'] for c in bindings],
               'target_bindings':[review_binding(self.case,c['claim_id']) for c in bindings],
               'input_refs':self._roots(p),'dependency_fingerprint':dependency_fingerprint(self.case,self._roots(p)),
               'output_ids':list(output_ids),'status':status,'postcondition':postcondition_observed,
               'limitations':[reason] if status=='limited' else [],'input_revision':expected_revision}
            if attempt_id in nodes:raise ValueError('Идентификатор запуска занят объектом')
            self.case['procedure_runs'].append(run)
            record={**payload,'target_bindings':bindings};self._success.setdefault(procedure_id,[]).append(record)
        elif status=='not_applicable':
            if p['mandatory_core'] or not reason.strip():raise ValueError('Обязательное ядро не отключается')
            self._success.setdefault(procedure_id,[]).append({**payload,'target_bindings':[]})
        elif not reason.strip():raise ValueError('Неуспех требует локализованной причины')
        self.spent_steps+=1;self.spent_cost+=cost;self._attempt_counts[procedure_id]=self._attempt_counts.get(procedure_id,0)+1
        if status in ('needs_data','needs_repair','blocked'):self._last_failure[procedure_id]=fp
        item=next(x for x in self.plan if x['procedure_id']==procedure_id)
        item.update(status=status,attempts=self._attempt_counts[procedure_id],reason=reason)
        self._attempts[attempt_id]=deepcopy(payload)
        if status=='blocked':self._set_state('blocked')
        self._rebuild();self._event({'event':'procedure_result',**payload,'target_bindings':bindings})
        return {'duplicate':False,'state':self.state,'next':self.next_step()}

    def accept_limited(self,procedure_id,consumer_id,*,review_id,reason):
        if self.state in STOPPED:raise ValueError('Запуск остановлен')
        nodes,groups=indexes(self.case);r=nodes.get(review_id)
        if not r or groups[review_id]!='reviews' or r['verdict']!='pass' or not review_current(self.case,r) or not reason.strip():raise ValueError('Нет актуальной проверки пригодности ограниченного входа')
        successes=self._success.get(procedure_id,[])
        targets={x for rec in successes for oid in rec['output_ids'] for x in nodes[oid]['claim_ids']}
        if r['target_claim_id'] not in targets:raise ValueError('Проверка другого ограниченного результата')
        self.accepted_limits[procedure_id+'->'+consumer_id]={'review_id':review_id,'reason':reason,'input_fingerprint':self._fingerprint(self.catalog[procedure_id])}
        self._event({'event':'limited_accepted','producer':procedure_id,'consumer':consumer_id,'review_id':review_id})

    def insert_repair(self,failed_id,*,reason):
        if self.state in STOPPED:raise ValueError('Ремонт не возобновляет остановленный запуск')
        if not reason.strip() or failed_id not in self._last_failure:raise ValueError('Нет локализованного неуспеха')
        route=self.catalog[failed_id]['failure_action']['route']
        if route not in self.catalog:raise ValueError('Неизвестный ремонт')
        # Record request; a retry still needs changed material and remaining global budget.
        self._event({'event':'repair_requested','failed_id':failed_id,'repair_id':route,'reason':reason})
        return {'repair_id':route,'requires_new_input':True,'resumed':False}

    def pending_target_obligations(self):
        missing=[]
        for item in self.plan:
            p=self.catalog[item['procedure_id']]
            if p.get('execution_scope')!='each_claim':continue
            valid=[b for rec in self._success.get(p['id'],[]) for b in rec.get('target_bindings',[])]
            missing.extend({'procedure_id':p['id'],**b} for b in self._bindings(p) if b not in valid)
        return missing

    def schedule_target_refresh(self,*,reason):
        if self.state in STOPPED:raise ValueError('Повторная проверка не возобновляет остановку')
        if not reason.strip():raise ValueError('Нужна причина')
        self._rebuild();self._event({'event':'refresh_requested','reason':reason})

    def stop(self,reason):
        if self.state=='closed' or not reason.strip():raise ValueError('Неверная остановка')
        self._set_state('partial');self._event({'event':'stopped','reason':reason})

    def resume(self,*,reason,continuation_attested=False):
        if self.state not in ('partial','degraded','blocked','closed'):raise ValueError('Запуск не остановлен')
        if not continuation_attested or not reason.strip():raise ValueError('Требуется решение о продолжении из доверенной среды')
        b=self.case['contract']['budget']
        if self.spent_steps>=b['step_limit']-b['reserve_steps']:raise ValueError('Бюджет не возобновлён')
        if any(i.code for i in validate_case(self.case)):raise ValueError('Не восстановлен договор случая')
        self._set_state('active');self._rebuild();self._event({'event':'resumed','reason':reason})

    def close(self,*,criterion_record):
        if self.state in STOPPED:raise ValueError('Запуск остановлен')
        self._rebuild()
        if not criterion_record.strip() or not all(x['status'] in TERMINAL for x in self.plan):raise ValueError('Не выполнены актуальные обязательства')
        if any(x['status']=='limited' and not self._accepted(x['procedure_id'],'CLOSURE') for x in self.plan):raise ValueError('Ограниченный выход не принят для полного завершения; используйте stop/partial')
        if self.pending_target_obligations():raise ValueError('Есть непроверенные версии атомов')
        closing=deepcopy(self.case);closing['status']='closed'
        issues=validate_case(closing)
        if issues:raise ValueError('Не пройден договор закрытия: '+','.join(x.code for x in issues))
        self._set_state('closed');self._event({'event':'closed','case_digest':digest(self.case),'criterion_record':criterion_record})

    def snapshot(self):
        meta={'schema_version':'3.0','state':self.state,'case_digest':digest(self.case),'case_id':self.case['case_id'],
          'plan':deepcopy(self.plan),'scoped_out':deepcopy(self.scoped_out),'triggers':deepcopy(self.triggers),
          'components':self.components,'spent_steps':self.spent_steps,'spent_cost':self.spent_cost,'max_attempts':self.max_attempts,
          'attempts':deepcopy(self._attempts),'attempt_counts':deepcopy(self._attempt_counts),'success':deepcopy(self._success),
          'last_failure':deepcopy(self._last_failure),'accepted_limits':deepcopy(self.accepted_limits),
          'history':deepcopy(self.history),'catalog_digest':digest(self.catalog_data)}
        self._event({'event':'checkpoint','state_digest':digest(meta),'case_digest':digest(self.case)})
        return {**meta,'events':deepcopy(self.events)}

    @staticmethod
    def verify_event_chain(events,*,trusted_tail=None):
        prev=None
        for i,e in enumerate(events):
            if e.get('sequence')!=i or e.get('previous_hash')!=prev or e.get('hash')!=digest({k:v for k,v in e.items() if k!='hash'}):return False
            prev=e['hash']
        return trusted_tail is None or prev==trusted_tail

    @classmethod
    def restore(cls,case,snapshot,*,trusted_tail=None,allow_untrusted=False):
        if trusted_tail is None and not allow_untrusted:raise ValueError('Нужна внешняя доверенная контрольная точка')
        if snapshot.get('schema_version')!='3.0' or snapshot.get('case_digest')!=digest(case):raise ValueError('Иной снимок случая')
        events=snapshot.get('events',[])
        if not events or not cls.verify_event_chain(events,trusted_tail=trusted_tail):raise ValueError('Нарушен журнал или доверенная точка')
        meta={k:v for k,v in snapshot.items() if k!='events'};last=events[-1]['payload']
        if last.get('event')!='checkpoint' or last.get('state_digest')!=digest(meta) or last.get('case_digest')!=digest(case):raise ValueError('Снимок не закреплён в доверенном событии')
        if validate_case(case):raise ValueError('Некорректное состояние')
        obj=cls.__new__(cls);obj.case=deepcopy(case);obj.catalog_data=load_json(ROOT/'data/procedures.json');obj.catalog={p['id']:p for p in obj.catalog_data['procedures']}
        if digest(obj.catalog_data)!=meta['catalog_digest']:raise ValueError('Каталог изменён: необходима миграция')
        for k in ('state','plan','scoped_out','triggers','components','spent_steps','spent_cost','max_attempts','accepted_limits','history'):setattr(obj,k,deepcopy(meta[k]))
        obj._attempts=deepcopy(meta['attempts']);obj._attempt_counts=deepcopy(meta['attempt_counts']);obj._success=deepcopy(meta['success']);obj._last_failure=deepcopy(meta['last_failure'])
        obj.events=deepcopy(events);obj.revision=len(events);obj._fp_cache={};obj._bindings_cache={}
        if case['status']!=obj.state:raise ValueError('Две расходящиеся машины состояния')
        if trusted_tail is None:obj._set_state('degraded')
        return obj

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','route','plan','next']);parser.add_argument('case',type=Path);parser.add_argument('--triggers',type=Path)
    a=parser.parse_args()
    try:
        case=load_json(a.case)
        if a.command=='validate':
            issues=validate_case(case);result={'valid_contract':not issues,'issues':[asdict(i) for i in issues],'semantic_validity':'not_established_by_schema'};code=int(bool(issues))
        elif a.command=='route':result=choose_profile(case['requested_profile'],case['risk']);code=0
        else:
            if not a.triggers:raise ValueError('Нужен --triggers')
            e=ProcedureEngine(case,load_json(a.triggers));result=e.snapshot() if a.command=='plan' else e.next_step();code=0
        print(json.dumps(result,ensure_ascii=False,indent=2));return code
    except (ValueError,TypeError,KeyError,OSError) as exc:print(json.dumps({'error':str(exc)},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
