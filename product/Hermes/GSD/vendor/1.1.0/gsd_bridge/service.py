"""Единая поверхность локальной интеграции. Внешние эффекты не исполняются."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import platform
import uuid
from typing import Any
from . import __version__
from .common import (ROOT, ENGINE, MAX_CONTEXT_BYTES, BridgeError, canonical, digest,
                     engine_modules, load, object_input, verify_tree)
from .store import Store
from .provider import generation_provider
from .composition import execute_components
from .context import ContextAssembler
from .lifecycle import Lifecycle
from .products import ProductRegistry
from .routes import route_status, next_request, accept_external

MODES = ['G', 'S', 'D', 'GS', 'GD', 'SD', 'GSD']

# Один источник схем используется CLI, MCP и модулем Hermes.
def _obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}
STR = {'type': 'string', 'minLength': 1}
OBJ = {'type': 'object'}
INT = {'type': 'integer', 'minimum': 0}
MODE = {'type': 'string', 'enum': MODES}
TOOLS = {
 'gsd_status': ('Состав, версии и границы доступного GSD.', _obj({})),
 'gsd_catalog': ('Поиск адресуемых определений; количество не означает исполнение.', _obj({
     'query': {'type': 'string'}, 'kind': {'enum': ['all','procedure','protocol','leaf','element']},
     'offset': INT, 'limit': {'type':'integer','minimum':1,'maximum':100}})),
 'gsd_contract': ('Полный договор процедуры, протокола, отдельного результата или исходного элемента.',
     _obj({'key': STR}, ['key'])),
 'gsd_context': ('Собрать исходные инструкции с полным обязательным контекстом; не обрезать.',
     _obj({'components': MODE, 'entry_keys': {'type':'array','items':STR},
           'byte_limit': {'type':'integer','minimum':1,'maximum':MAX_CONTEXT_BYTES},
           'procedure_ids': {'type':'array','items':STR},
           'profile': {'enum':['standard','engineering']}}, ['components'])),
 'gsd_intake': ('Зарегистрировать сырой запрос как недоверенные данные, не создавать факты и права.', _obj({'text':STR,'components':MODE}, ['text','components'])),
 'gsd_validate_case': ('Проверить схему случая и межобъектные условия; не предметную истинность.',
     _obj({'case':OBJ}, ['case'])),
 'gsd_execute': ('Выполнить исходные конечные операции G/S/D. Смысловые операции требуют агента.',
     _obj({'components':MODE, 'request':OBJ, 'request_id':STR}, ['components','request','request_id'])),
 'gsd_case_create': ('Создать сохраняемый случай исходного контроллера процедур.',
     _obj({'case':OBJ,'triggers':OBJ,'components':MODE,'request_id':STR}, ['case','triggers','components','request_id'])),
 'gsd_case_get': ('Получить сохранённый случай и проверенный снимок.', _obj({'run_id':STR}, ['run_id'])),
 'gsd_case_next': ('Получить следующую процедуру и её фактические входные обязательства.', _obj({'run_id':STR}, ['run_id'])),
 'gsd_case_change': ('Транзакционно обновить случай, зафиксировать результат, остановить или закрыть его.',
     _obj({'run_id':STR,'request_id':STR,'expected_store_revision':INT,
           'operation':{'enum':['update','commit','stop','close','accept_limited','insert_repair','refresh']},
           'payload':OBJ}, ['run_id','request_id','expected_store_revision','operation','payload'])),
 'gsd_handoff_validate': ('Проверить заголовок передачи. Не доставляет продукт и не резервирует ресурс.',
     _obj({'message':OBJ}, ['message'])),
 'gsd_action_check': ('Проверить границу решения без доверенного полномочия. Не даёт разрешение и не исполняет действие.',
     _obj({'case':OBJ,'decision_id':STR}, ['case','decision_id'])),
 'gsd_product_register': ('Зарегистрировать исходный продукт без повышения статуса и с сохранением входов.',
     _obj({'namespace':STR,'logical_key':STR,'product':OBJ,'input_objects':OBJ,
           'origin_component':{'enum':['G','S','D']},'origin_ref':STR,
           'expected_version':INT,'request_id':STR},
          ['namespace','logical_key','product','input_objects','origin_component','origin_ref','expected_version','request_id'])),
 'gsd_product_get': ('Получить зарегистрированный продукт; история не считается текущим результатом.',
     _obj({'product_id':STR,'version':{'type':'integer','minimum':1},'current_required':{'type':'boolean'}}, ['product_id'])),
 'gsd_product_handoff': ('Собрать полный пакет передачи из текущего зарегистрированного продукта. Не выполняет доставку.',
     _obj({'product_id':STR,'product_version':{'type':'integer','minimum':1},'header':OBJ,
           'input_objects':OBJ,'context':OBJ,'standard':OBJ},
          ['product_id','product_version','header','input_objects','context','standard'])),
}

class Service:
    def __init__(self):
        self.modules = engine_modules()
        self.corpus = ContextAssembler(self.modules)
        self.lifecycle_instance = None
        self.store_instance = None
        self.registry = load(ROOT / 'contracts/catalog.json')

    @property
    def store(self):
        if self.store_instance is None:
            self.store_instance = Store()
        return self.store_instance

    @property
    def lifecycle(self):
        if self.lifecycle_instance is None:
            self.lifecycle_instance = Lifecycle(self.modules, self.store, self.status()['engine_manifest_sha256'])
        return self.lifecycle_instance

    @property
    def products(self):
        return ProductRegistry(self.store, self.modules['triad'])

    def call(self, name: str, arguments: Any) -> dict:
        try:
            if not isinstance(name, str) or name not in TOOLS:
                raise BridgeError('UNKNOWN_TOOL', 'Неизвестный инструмент')
            args = object_input(arguments)
            from jsonschema import Draft202012Validator
            errors = list(Draft202012Validator(TOOLS[name][1]).iter_errors(args))
            if errors:
                raise BridgeError('INVALID_INPUT', errors[0].message)
            # JSON Schema допускает 1.0 как integer; публичный договор — нет.
            for key in ('offset','limit','byte_limit','expected_store_revision','expected_version','product_version','version'):
                if key in args and type(args[key]) is not int:
                    raise BridgeError('INVALID_INPUT', key + ': требуется целое, не bool/float')
            result = getattr(self, name.removeprefix('gsd_'))(**args)
            return {'ok': True, 'integration_version': __version__, 'result': result}
        except (BridgeError, ValueError, KeyError, TypeError, AssertionError, AttributeError, OSError) as exc:
            return {'ok': False, 'integration_version': __version__, 'error': {
                'code': getattr(exc, 'code', 'CONTRACT_REJECTED'), 'message': str(exc)},
                'external_effect_performed': False}

    def status(self):
        return {'integration_version': __version__, 'engine': load(ENGINE/'data/release.json'),
            'engine_manifest_sha256': hashlib.sha256((ENGINE/'manifest.json').read_bytes()).hexdigest(),
            'engine_files_verified_at_process_start': True, 'python': platform.python_version(),
            'modes': MODES, 'catalog_entries': len(self.registry['entries']),
            'persistent_state_configured': bool(os.environ.get('GSD_STATE_DIR') and os.environ.get('GSD_TRUST_KEY_FILE')),
            'generation_provider_configured': bool(os.environ.get('GSD_PROVIDER_CONFIG')),
            'arbitrary_semantic_execution': 'host_agent_or_domain_reviewer',
            'external_effects': 'not_implemented', 'host_wide_enforcement': 'requires_host_controls',
            'upstream_source_modified': False,
            'integration_contract': '1.1.0', 'procedure_routes': 'local_plus_explicit_external_obligations',
            'context_profiles': ['standard','engineering'],
            'original_adapter_1_2_included': False,
            'external_procedure_executor_configured': bool(os.environ.get('GSD_HOST_POLICY')),
            'external_effect_capability': 'unavailable_fail_closed',
            'case_family_budget': 'persistent_local_only_not_host_wide'}

    def catalog(self, query='', kind='all', offset=0, limit=20):
        query = query.casefold()
        entries = [r for r in self.registry['entries'] if (kind == 'all' or r['kind'] == kind)
                   and (not query or query in (r['key']+' '+r['title']).casefold())]
        return {'total': len(entries), 'offset': offset, 'entries': entries[offset:offset+limit],
                'next_offset': offset+limit if offset+limit < len(entries) else None}

    def contract(self, key):
        rows = [r for r in self.registry['entries'] if r['key'] == key]
        if not rows:
            # Допускается точный исходный ключ, который разрешает само ядро.
            return self.corpus.operation_contract(key)
        row = rows[0]
        if row['kind'] == 'element':
            return self.corpus.operation_contract(row['source_key'])
        data = load(ENGINE / row['path'])
        return data[row['collection']][row['index']]

    def context(self, components, entry_keys=None, byte_limit=1500000, procedure_ids=None, profile='standard'):
        manifest = self.corpus.manifest(components=components, entry_keys=entry_keys or [],
                                        procedure_ids=procedure_ids or [], profile=profile)
        assembled = self.corpus.assemble_context(manifest, byte_limit=byte_limit)
        return {'manifest':manifest, **assembled,
                'delivery_requirement':'Хост должен подтвердить доставку полного текста; сокращённый вывод не является загрузкой'}

    def intake(self,text,components):
        return self.modules['triad'].intake_raw(text,requested_components=components)

    def validate_case(self, case):
        issues = self.modules['records'].validate_case(case)
        return {'valid_contract':not issues,'issues':[asdict(i) for i in issues],
                'semantic_validity':'not_established_by_schema'}

    def _request_digest(self, args):
        return digest({'bridge':__version__, 'engine_manifest':self.status()['engine_manifest_sha256'], 'input':args})

    def execute(self, components, request, request_id):
        fingerprint = self._request_digest([components,request])
        # Резерв запроса сохраняется ДО возможного внешнего вызова модели.
        # Сбой процесса не превращает повтор в незаметное повторное исполнение.
        with self.store.transaction() as con:
            prior = self.store.prior(con,'triad',request_id,fingerprint)
            if prior is not None:
                return {**prior,'duplicate':True}
            self.store.remember(con,'triad',request_id,fingerprint,{
                'effective_status':'in_progress_or_outcome_unknown',
                'automatic_retry_forbidden':True,'duplicate':False,
                'request_digest':fingerprint})
        try:
            result=self._execute_once(components,request)
        except Exception as exc:
            result={'effective_status':'failed','error':{'code':getattr(exc,'code','EXECUTION_FAILED'),
                    'message':str(exc)},'external_effect_performed':False,
                    'automatic_retry_forbidden':True,'duplicate':False}
        with self.store.transaction() as con:
            self.store.complete(con,'triad',request_id,fingerprint,result)
        return result

    def _execute_once(self, components, request):
        triad = self.modules['triad']
        limits = request.get('execution_budget', {'step_limit':100,'reserve_steps':1})
        if not isinstance(limits,dict) or type(limits.get('step_limit')) is not int or limits['step_limit'] > 10000:
            raise BridgeError('BUDGET_LIMIT', 'step_limit должен быть целым не более 10000')
        if len(request.get('candidates',[])) > 500 or len(request.get('observations',[])) > 1000:
            raise BridgeError('INPUT_TOO_LARGE', 'Сократите конечное поле явным разбиением задачи')
        req = deepcopy(request)
        if 'G' in components:
            gen = req.get('generation')
            if not isinstance(gen, dict):
                raise BridgeError('INVALID_INPUT','Отсутствует generation')
            if type(gen.get('scan_budget')) is not int or not 0 < gen['scan_budget'] <= 10000:
                raise BridgeError('BUDGET_LIMIT','scan_budget: целое 1–10000')
            if type(gen.get('max_candidates')) is not int or not 0 < gen['max_candidates'] <= 500:
                raise BridgeError('BUDGET_LIMIT','max_candidates: целое 1–500')
            if gen.get('scope') != req.get('scope'):
                raise BridgeError('SCOPE_MISMATCH','Области генерации и сравнения должны совпадать')
        provider, receipt = (None, None)
        if 'G' in components and req['generation'].get('method') == 'agent':
            provider, receipt = generation_provider(self.modules, req['generation'])
        try:
            output = execute_components(triad, components, req, generation_provider=provider)
            missing = [c for c,v in output.get('outputs',{}).items()
                       if v.get('status') in ('awaiting_provider','awaiting_dependency') or v.get('missing')]
            result = {'engine_result':output, 'provider_receipt':receipt,
                      'effective_status':'awaiting_provider_or_dependency' if missing else 'bounded_local_execution',
                      'missing_components':missing, 'semantic_acceptance':'not_established',
                      'external_effect_performed':False, 'duplicate':False,
                      'resource_scope':'Один execute; общий бюджет агента контролирует хост'}
        except Exception as exc:
            # Не повторять автоматически вызов поставщика после неизвестного исхода.
            result = {'effective_status':'failed', 'error':{'code':getattr(exc,'code','EXECUTION_FAILED'),
                'message':str(exc)}, 'provider_receipt':receipt, 'external_effect_performed':False,
                'duplicate':False, 'automatic_retry_forbidden':True}
        return result

    def case_create(self, case, triggers, components, request_id):
        fp = self._request_digest([case, triggers, components])
        return self.lifecycle.create(case, triggers, components, request_id, fp)

    def _save(self, con, run_id, engine, revision):
        return self.lifecycle.save(con, run_id, engine, revision)

    def _restore(self, con, run_id):
        return self.lifecycle.restore(con, run_id)

    def case_get(self,run_id):
        with self.store.transaction() as con:
            rev,engine = self._restore(con,run_id)
            return {'run_id':run_id,'store_revision':rev,'case':engine.case,'state':engine.state,
                    'pending_target_obligations':engine.pending_target_obligations(),
                    'plan':engine.plan,'spent_steps':engine.spent_steps,'spent_cost':engine.spent_cost,
                    'procedure_route':route_status(engine), 'family':self.lifecycle.family_status(con, engine)}

    def case_next(self,run_id):
        with self.store.transaction() as con:
            rev,engine = self._restore(con,run_id)
            result = next_request(engine, self.corpus)
            saved = self._save(con,run_id,engine,rev+1)
            return {**saved,'next':result}

    def case_change(self,run_id,request_id,expected_store_revision,operation,payload):
        fp = self._request_digest([run_id,expected_store_revision,operation,payload])
        with self.store.transaction() as con:
            prior = self.store.prior(con,run_id,request_id,fp)
            if prior is not None:
                return {**prior,'duplicate':True}
            rev,engine = self._restore(con,run_id)
            if rev != expected_store_revision:
                raise BridgeError('STALE_REVISION','Ожидаемая редакция хранилища не совпадает')
            error = None
            try:
                if operation == 'update':
                    new = payload['case']
                    oldbudget=engine.case['contract']['budget']; newbudget=new['contract']['budget']
                    if new['contract']['intended_use'] != 'analysis_only':
                        raise BridgeError('ANALYSIS_ONLY','Нельзя повысить право через данные случая')
                    if newbudget != oldbudget:
                        raise BridgeError('HOST_CONTROL_REQUIRED','Изменение бюджета не предоставлено модельному инструменту')
                    if new.get('authorities') != engine.case.get('authorities'):
                        raise BridgeError('HOST_CONTROL_REQUIRED','Полномочия не создаются модельным инструментом')
                    base=self.modules['_base']
                    old=base.choose_profile(engine.case['requested_profile'],engine.case['risk'])
                    newroute=base.choose_profile(new['requested_profile'],new['risk'])
                    if base.PROFILES.index(newroute['selected']) < base.PROFILES.index(old['selected']):
                        raise BridgeError('HOST_CONTROL_REQUIRED','Снижение профиля требует решения хоста')
                    engine.update_case(new,expected_revision=payload['expected_case_revision'])
                elif operation == 'commit':
                    allowed={'procedure_id','attempt_id','status','output_ids','expected_revision',
                             'postcondition_observed','reason','cost'}
                    if set(payload)-allowed:
                        raise BridgeError('INVALID_INPUT','Неизвестные поля commit')
                    self.lifecycle.check_commit(con, engine, payload)
                    engine.commit(**payload)
                elif operation == 'stop':
                    engine.stop(payload['reason'])
                elif operation == 'close':
                    criterion=payload['criterion_record']
                    artifacts={a['id']:a for a in engine.case['artifacts']}
                    record=artifacts.get(criterion)
                    accepted=any(r['procedure_id']=='SYNTHESIS.05' and r['status'] in ('pass','limited')
                                 and criterion in r['output_ids'] for r in engine.case['procedure_runs'])
                    if not record or record['kind']!='ClosureRecord' or not accepted:
                        raise BridgeError('CLOSURE_RECORD_REQUIRED','Нужен адресный ClosureRecord принятой процедуры SYNTHESIS.05')
                    engine.close(criterion_record=criterion)
                elif operation == 'accept_limited':
                    engine.accept_limited(**payload)
                elif operation == 'insert_repair':
                    engine.insert_repair(**payload)
                elif operation == 'refresh':
                    engine.schedule_target_refresh(reason=payload['reason'])
                else:
                    raise BridgeError('INVALID_OPERATION','Неизвестная операция изменения')
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                # Даже отказ может перевести ядро в stop; состояние отказа сохраняется.
                error={'code':getattr(exc,'code','CONTRACT_REJECTED'),'message':str(exc)}
            result=self._save(con,run_id,engine,rev+1)
            result.update({'operation_accepted':error is None,'error':error,'duplicate':False})
            self.store.remember(con,run_id,request_id,fp,result)
            return result

    def resume_by_host(self,run_id,expected_store_revision,reason):
        """Только отдельная команда оператора; не публикуется как инструмент агента."""
        with self.store.transaction() as con:
            rev,engine=self._restore(con,run_id)
            if rev != expected_store_revision:
                raise BridgeError('STALE_REVISION','Редакция изменилась')
            self.lifecycle.check_commit(con, engine, {})
            engine.resume(reason=reason,continuation_attested=True)
            return self._save(con,run_id,engine,rev+1)

    def handoff_validate(self,message):
        self.modules['triad'].validate_handoff_header(message)
        return {'header_valid':True,'payload_validated':False,'delivery_performed':False,
                'budget_reserved':False,
                'next_required':'HandoffChannel.send с полными objects и общим бюджетом принимающего хоста'}

    def action_check(self,case,decision_id):
        result=self.modules['records'].action_boundary(case,decision_id,trusted_authority_bindings={})
        return {**result,'adapter_permits_execution':False}

    def new_run_by_host(self, **arguments):
        return self.lifecycle.new_run_by_host(**arguments)

    def external_commit_by_host(self, receipt):
        return accept_external(self, receipt)

    def migrate_by_host(self, **arguments):
        return self.lifecycle.migrate_by_host(**arguments)

    def product_register(self, **arguments):
        return self.products.register(**arguments)

    def product_get(self, product_id, version=None, current_required=True):
        return {'product': self.products.get(product_id, version, current_required=current_required),
                'semantic_verification': 'not_established_by_registration'}

    def product_handoff(self, **arguments):
        return self.products.prepare_handoff(**arguments)
