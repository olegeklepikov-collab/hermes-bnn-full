"""Адресные проверки GSD-I01–I07. Нет вызовов модели или действующего Hermes."""
from __future__ import annotations
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import test_bridge as baseline
from gsd_bridge.common import BridgeError, canonical, digest, load, verify_tree
from gsd_bridge.service import Service, TOOLS, MODES
from gsd_bridge.routes import signature
from gsd_bridge.products import source_status

ROOT = baseline.ROOT
fixture = baseline.fixture


class RemediationTests(unittest.TestCase):
    setUp = baseline.BridgeTests.setUp
    tearDown = baseline.BridgeTests.tearDown
    call = baseline.BridgeTests.call
    change = baseline.BridgeTests.change
    cli = baseline.BridgeTests.cli
    configure = baseline.BridgeTests.configure

    def create(self, mode='GSD', suffix='', **case_changes):
        a = fixture('case_create.json')
        a['components'] = mode
        a['case']['case_id'] += suffix
        a['request_id'] += suffix
        a['case'].update(case_changes)
        return self.call('gsd_case_create', a)

    def missing(self, policy=None):
        a = fixture('modes/GSD.json')
        a['request']['generation']['method'] = 'agent'
        if policy:
            a['request']['generation_unavailable_policy'] = policy
        return a

    def register(self, product=None, logical_key='result', **overrides):
        a = {'namespace': 'case-one', 'logical_key': logical_key,
             'product': product or {'type': 'Example', 'content': 'Не проверено'},
             'input_objects': {'INPUT.1': {'id':'INPUT.1','version':1,'text':'Вход'}},
             'origin_component':'S', 'origin_ref':'EXEC.1', 'expected_version':0, 'request_id':'REGISTER.'+logical_key}
        a.update(overrides)
        return self.call('gsd_product_register', a)

    def header(self, suffix='1'):
        return {'id':'HANDOFF.'+suffix,'receiver':'D','component_versions':{'G':'3.0','S':'3.0','D':'3.0'},
            'corpus_digest':'c'*64,'risk_floor':'eMVP','deadline':'2099-01-01T00:00:00Z',
            'budget_reservation':'RESERVATION.'+suffix,'budget_amount':1,
            'residuals':self.service.modules['triad'].residuals()}

    def transfer_args(self, product, suffix='1'):
        return {'product_id':product['id'],'product_version':product['version'],
            'header':self.header(suffix), 'input_objects':{'INPUT.1':{'id':'INPUT.1','version':1,'text':'Вход'}},
            'context':{'scope':'Проверка передачи'},'standard':{'rule':'Не повышать статус'}}

    def external_fixture(self, mode='G'):
        run = self.create(mode)
        nxt = self.call('gsd_case_next', {'run_id':run['run_id']})
        request = nxt['next']['external_request']
        case = self.call('gsd_case_get', {'run_id':run['run_id']})['case']
        case['revision'] += 1
        case['artifacts'].append({'id':'EXTERNAL.BOOT.OUT','version':1,'kind':'Запись комплектации',
            'context_id':case['contexts'][0]['id'],'summary':json.dumps({'manifest':self.service.status()['engine_manifest_sha256'],
            'verified':verify_tree(ROOT/'engine')['valid']},ensure_ascii=False),
            'claim_ids':[],'evidence_ids':[],'limitations':['Синтетическая проверка приёмки внешней квитанции'],
            'input_fingerprint':request['input_fingerprint'],'semantic_result_refs':[],'accepted_limitations_by':[]})
        updated = self.change(nxt,'update',{'case':case,'expected_case_revision':0},'external-artifact')
        self.assertTrue(updated['operation_accepted'],updated)
        key = self.tmp/'executor.key';key.write_bytes(os.urandom(32));key.chmod(0o600)
        policy = self.tmp/'host-policy.json'
        policy.write_text(json.dumps({'contract':'gsd.host-policy/1','procedure_executors':{
            'external-D':{'enabled':True,'components':['D'],'key_file':str(key)}}}))
        os.environ['GSD_HOST_POLICY'] = str(policy)
        receipt = {'id':'EXT.BOOT.1','producer':'external-D','run_id':run['run_id'],'procedure_id':'BOOT.01',
            'case_revision':1,'input_fingerprint':request['input_fingerprint'],
            'context_manifest_digest':request['context_manifest_digest'],'context_text_sha256':request['context_text_sha256'],
            'context_delivery_attested':True,'output_digests':{'EXTERNAL.BOOT.OUT':digest(case['artifacts'][-1])},
            'status':'pass','postcondition_observed':'Наличие файлов и версии сопоставлены с исходным манифестом',
            'reason':'','cost':3.5,'deadline':'2099-01-01T00:00:00Z'}
        receipt['signature'] = signature(receipt,key.read_bytes())
        return updated, receipt, key, policy

    def resign(self, receipt, key):
        receipt['signature'] = signature({k:v for k,v in receipt.items() if k!='signature'}, key.read_bytes())

    def test_I01_missing_G_blocks_before_S_D_invocation(self):
        triad = self.service.modules['triad']
        with patch.object(triad.StrictComponent,'compare',side_effect=AssertionError('S must not run')), \
             patch.object(triad.DiagnosticComponent,'run',side_effect=AssertionError('D must not run')):
            value = self.call('gsd_execute',self.missing())['engine_result']
        self.assertEqual(value['invoked_components'],['G'])
        self.assertEqual(value['executed_components'],[])
        self.assertEqual(value['blocked_components'],['S','D'])
        self.assertEqual(len(value['input_candidates']),2)

    def test_I01_explicit_fallback_keeps_G_open_and_preserves_inputs(self):
        a = self.missing('use_supplied_candidates');before=deepcopy(a)
        value = self.call('gsd_execute',a)
        out=value['engine_result']
        self.assertEqual(a,before)
        self.assertEqual(out['branch'],'explicit_supplied_candidates_without_G')
        self.assertEqual(out['executed_components'],['S','D'])
        self.assertEqual(len(out['outputs']['S']['rows']),2)
        self.assertEqual(out['candidate_field'],a['request']['candidates'])
        self.assertEqual(out['open_obligations'][0]['component'],'G')
        self.assertEqual(value['effective_status'],'awaiting_provider_or_dependency')
        self.assertTrue(all(p['source']=='request.candidates' for p in out['candidate_provenance']))

    def test_I01_empty_fallback_does_not_invoke_dependents(self):
        a=self.missing('use_supplied_candidates');a['request']['candidates']=[]
        result=self.call('gsd_execute',a)['engine_result']
        self.assertEqual(result['executed_components'],[])
        self.assertEqual(result['blocked_components'],['S','D'])

    def test_I01_supplied_data_not_new_semantic_generation(self):
        result=self.call('gsd_execute',fixture('modes/G.json'))['engine_result']
        self.assertEqual(result['executed_components'],['G'])
        self.assertFalse(result['semantic_generation_performed'])

    def test_I01_invalid_policy_rejected(self):
        a=self.missing('pretend_G_succeeded')
        self.assertEqual(self.call('gsd_execute',a)['effective_status'],'failed')

    def test_I01_D_without_review_not_invoked(self):
        triad=self.service.modules['triad']
        with patch.object(triad.DiagnosticComponent,'run',side_effect=AssertionError('no review')):
            out=self.call('gsd_execute',fixture('modes/D.json'))['engine_result']
        self.assertEqual(out['invoked_components'],[])
        self.assertEqual(out['outputs']['D']['status'],'awaiting_dependency')

    def test_I02_all_four_cross_component_references(self):
        for mode,key in [('D','strict:C-D011'),('D','strict:C-J010'),('G','strict:C-A009'),('G','strict:C-G003')]:
            with self.subTest(mode=mode,key=key):
                out=self.call('gsd_context',{'components':mode,'entry_keys':[key]})
                m=out['manifest']
                self.assertEqual(m['components'],list(mode))
                self.assertNotIn('components/S_SYSTEM.md',[x['path'] for x in m['files']])
                self.assertTrue(any(x['foreign_component_reference'] for x in m['entries']))
                self.assertTrue(all(x['use']=='reference_only' and not x['executes_component'] for x in m['entries']))
                self.assertIn(self.service.corpus.base.exact(key)['definition'],out['text'])

    def test_I02_procedure_contract_and_dependencies_delivered(self):
        out=self.call('gsd_context',{'components':'G','procedure_ids':['STRUCTURE.04']})
        rows=out['manifest']['procedure_contracts']
        self.assertIn('STRUCTURE.04',[x['id'] for x in rows])
        self.assertIn('ATOM.17',[x['id'] for x in rows])
        self.assertTrue(any(x['execution']=='external_product_required_when_active' for x in rows))

    def test_I02_short_generative_anchors_resolve_uniquely(self):
        m=self.service.corpus.manifest(components='G',entry_keys=['generative:GA-07'])
        exact=self.service.corpus.base.lookup('generative','GA-07')[0]['key']
        self.assertIn({'requested':'generative:GA-07','resolved':exact,
                       'rule':'unique_source_identifier_or_registered_alias'},m['source_resolutions'])
        out=self.service.corpus.assemble_context(m,byte_limit=8000000)
        self.assertIn(self.service.corpus.base.exact(exact)['definition'],out['text'])

    def test_I02_ambiguous_source_identifier_not_guessed(self):
        with patch.object(self.service.corpus.base,'lookup',return_value=[{'key':'a'},{'key':'b'}]):
            with self.assertRaises(BridgeError) as caught:
                self.service.corpus.exact('generative:GA-07')
            self.assertEqual(caught.exception.code,'AMBIGUOUS_REFERENCE')

    def test_I02_foreign_active_instruction_remains_forbidden(self):
        with self.assertRaises(BridgeError):
            self.service.corpus.manifest(components='G',file_paths=['components/S_SYSTEM.md'])

    def test_I02_forged_incomplete_manifest_rejected_even_with_rehashed_body(self):
        m=self.service.corpus.manifest(components='G',procedure_ids=['STRUCTURE.04'])
        m['entries'].pop()
        m['digest']=digest({k:v for k,v in m.items() if k!='digest'})
        with self.assertRaises(BridgeError):
            self.service.corpus.assemble_context(m,byte_limit=8000000)

    def test_I02_incomplete_delivery_receipt_rejected(self):
        out=self.call('gsd_context',{'components':'G'})
        missing=dict(out['loaded_entries']);missing.pop(next(iter(missing)))
        with self.assertRaises(BridgeError):
            self.service.corpus.verify_manifest(out['manifest'],loaded_files=out['loaded_files'],loaded_entries=missing)

    def test_I03_seven_procedure_routes_keep_all_obligations(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                run=self.create(mode,'.'+mode)
                actual=self.call('gsd_case_get',{'run_id':run['run_id']})
                original=self.service.modules['engine'].ProcedureEngine(actual['case'],fixture('case_create.json')['triggers'],components=mode)
                self.assertEqual(actual['plan'],original.plan)
                route=actual['procedure_route']
                self.assertEqual(len(route['local_obligations'])+len(route['external_obligations']),len(original.plan))
                nxt=self.call('gsd_case_next',{'run_id':run['run_id']})['next']
                if 'D' in mode:
                    self.assertEqual(nxt['procedure']['id'],'BOOT.01')
                else:
                    self.assertIsNone(nxt['procedure'])
                    self.assertEqual(nxt['external_request']['procedure']['id'],'BOOT.01')
                    self.assertFalse(nxt['external_request']['completed'])
                    self.assertEqual(set(nxt['external_request']['local_components_unchanged']),set(mode))

    def test_I03_signed_external_product_makes_real_procedural_progress(self):
        run,receipt,key,policy=self.external_fixture()
        result=self.service.external_commit_by_host(receipt)
        self.assertTrue(result['operation_accepted'],result)
        self.assertEqual(result['spent_steps'],1)
        case=self.call('gsd_case_get',{'run_id':run['run_id']})
        self.assertEqual(case['case']['procedure_runs'][0]['procedure_id'],'BOOT.01')
        self.assertEqual(case['procedure_route']['route'],'G')
        nxt=self.call('gsd_case_next',{'run_id':run['run_id']})['next']
        self.assertEqual(nxt['external_request']['procedure']['id'],'BOOT.02')

    def test_I03_external_replay_not_double_counted(self):
        _,receipt,_,_=self.external_fixture()
        first=self.service.external_commit_by_host(receipt)
        again=self.service.external_commit_by_host(receipt)
        self.assertTrue(again['duplicate']);self.assertEqual(first['family_spent_steps'],again['family_spent_steps'])

    def test_I03_external_signature_tamper_rejected(self):
        _,receipt,_,_=self.external_fixture();receipt['status']='limited'
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'EXTERNAL_SIGNATURE')

    def test_I03_external_revocation_checked_before_duplicate(self):
        _,receipt,_,policy=self.external_fixture();self.service.external_commit_by_host(receipt)
        value=load(policy);value['procedure_executors']['external-D']['enabled']=False;policy.write_bytes(canonical(value))
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'EXECUTOR_UNTRUSTED_OR_REVOKED')

    def test_I03_external_wrong_component_rejected(self):
        _,receipt,_,policy=self.external_fixture()
        value=load(policy);value['procedure_executors']['external-D']['components']=['S'];policy.write_bytes(canonical(value))
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'EXECUTOR_SCOPE')

    def test_I03_external_requires_context_delivery_attestation(self):
        _,receipt,key,_=self.external_fixture();receipt['context_delivery_attested']=False;self.resign(receipt,key)
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'CONTEXT_DELIVERY_REQUIRED')

    def test_I03_external_expired_or_stale_context_rejected(self):
        _,receipt,key,_=self.external_fixture()
        for field,value in [('deadline','2020-01-01T00:00:00Z'),('context_manifest_digest','f'*64)]:
            bad=deepcopy(receipt);bad[field]=value;self.resign(bad,key)
            with self.subTest(field=field),self.assertRaises(BridgeError):self.service.external_commit_by_host(bad)

    def test_I03_external_output_substitution_rejected(self):
        _,receipt,key,_=self.external_fixture();receipt['output_digests']['EXTERNAL.BOOT.OUT']='e'*64;self.resign(receipt,key)
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'EXTERNAL_OUTPUT_CHANGED')

    def test_I03_external_not_exposed_to_model(self):
        for name in ['gsd_external_commit','gsd_host_command','gsd_new_run','gsd_migrate_state']:
            self.assertNotIn(name,TOOLS)
            self.assertFalse(self.service.call(name,{})['ok'])

    def test_I03_missing_host_policy_does_not_accept_foreign_product(self):
        _,receipt,_,_=self.external_fixture();os.environ['GSD_HOST_POLICY']=''
        with self.assertRaises(BridgeError) as exc:self.service.external_commit_by_host(receipt)
        self.assertEqual(exc.exception.code,'HOST_POLICY_REQUIRED')

    def test_I04_engineering_index_all_sections_match_source(self):
        index=load(ROOT/'contracts/engineering_sections.json')
        raw=(ROOT/'engine'/index['source_path']).read_bytes();lines=raw.decode().splitlines(keepends=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),index['source_sha256'])
        self.assertEqual(len(index['sections']),305)
        self.assertEqual(len([s for s in index['sections'] if s['level']==2]),69)
        for section in index['sections']:
            actual=''.join(lines[section['start_line']-1:section['end_line']]).encode()
            self.assertEqual(hashlib.sha256(actual).hexdigest(),section['sha256'])

    def test_I04_engineering_context_has_entire_source_and_core(self):
        out=self.call('gsd_context',{'components':'GSD','profile':'engineering'})
        index=load(ROOT/'contracts/engineering_sections.json')
        source=(ROOT/'engine'/index['source_path']).read_text()
        self.assertIn(source,out['text'])
        self.assertEqual(out['manifest']['engineering_closure']['mandatory_core'],['0','3','5','46','48','50','57','58'])
        self.assertFalse(out['model_delivery_verified'])

    def test_I04_section_address_resolves_exact_text(self):
        out=self.call('gsd_contract',{'key':'engineering:section:24.90'})
        self.assertIn('К24',out['operation_exact_source'])
        self.assertFalse(out['authority_granted'])

    def test_I04_engineering_key_without_profile_rejected(self):
        out=self.service.call('gsd_context',{'components':'G','entry_keys':['engineering:section:24']})
        self.assertFalse(out['ok']);self.assertEqual(out['error']['code'],'ENGINEERING_PROFILE_REQUIRED')

    def test_I04_exact_byte_limit_not_silent_truncation(self):
        a={'components':'GSD','profile':'engineering'}
        out=self.call('gsd_context',a)
        exact=self.call('gsd_context',{**a,'byte_limit':out['bytes']})
        self.assertEqual(exact['text'],out['text'])
        rejected=self.service.call('gsd_context',{**a,'byte_limit':out['bytes']-1})
        self.assertFalse(rejected['ok']);self.assertNotIn('result',rejected)

    def test_I04_standard_G_does_not_load_engineering_by_default(self):
        out=self.call('gsd_context',{'components':'G'})
        self.assertIsNone(out['manifest']['engineering_closure'])
        self.assertNotIn('engine/sources/deep_agent_personality_ai_agents_engineer.md',out['loaded_files'])

    def test_I05_native_formal_principle_diagnostic_products_are_transmitted(self):
        triad=self.service.modules['triad']
        req=fixture('strict_derivation.json')['request']
        formal=triad.StrictComponent().derive(req['premises'],req['implications'],scope=req['scope'])
        proposal={'id':'PC1','statement':'Из отчёта не следует подтверждение содержания','primary_C_ID':'C-D002',
            'D_path':['D1'],'D_required_reason':'Исследование источника','M_path':['M1'],'M_required_reason':'Проверка перехода',
            'E_ID':'E001','Q_ID':'Q1','register_profile':{k:'Явная область '+k for k in 'OEAD'},'S0_pass_reason':'Форма одного различения',
            'H_role':'none','H_not_used_for_validation':True,'negative_grammar_hits':[]}
        principle=triad.StrictComponent().principle_contract(proposal)
        diagnostic=self.call('gsd_execute',fixture('modes/GSD.json'))['engine_result']['outputs']['D']
        for i,product in enumerate([formal,principle,diagnostic]):
            with self.subTest(type=product['type']):
                registered=self.register(product,logical_key=str(i))['product']
                self.assertEqual(registered['product'],product)
                self.assertEqual(registered['status'],product.get('status','unreviewed'))
                args=self.transfer_args(registered,str(i))
                channel=triad.HandoffChannel(component_versions=args['header']['component_versions'],corpus_digest='c'*64,budget=triad.SharedBudget(10))
                got=self.service.products.deliver(channel=channel,receiver='D',**args)
                self.assertEqual(got['receipt']['state'],'accepted_for_processing')
                self.assertFalse(got['receipt']['epistemic_promotion'])
                self.assertFalse(got['semantic_execution_performed'])

    def test_I05_description_M_not_promoted(self):
        p=self.register({'type':'FormalDerivation','M':'Достоверно выполнено по словам поставщика'})['product']
        self.assertEqual(p['status'],'unreviewed')

    def test_I05_registration_same_content_new_request_is_idempotent(self):
        first=self.register()['product'];again=self.register(request_id='REGISTER.again')
        self.assertTrue(again['duplicate']);self.assertEqual(again['product'],first)

    def test_I05_changed_content_requires_expected_current_version(self):
        first=self.register()['product']
        bad=self.service.call('gsd_product_register',{'namespace':'case-one','logical_key':'result','product':{'x':2},
            'input_objects':{},'origin_component':'S','origin_ref':'EXEC.1','expected_version':0,'request_id':'R2'})
        self.assertFalse(bad['ok'])
        second=self.register({'x':2},expected_version=1,request_id='R3')['product']
        self.assertEqual(second['id'],first['id']);self.assertEqual(second['version'],2)

    def test_I05_history_preserved_but_stale_product_not_transferable(self):
        first=self.register()['product'];self.register({'x':2},expected_version=1,request_id='R2')
        old=self.call('gsd_product_get',{'product_id':first['id'],'version':1,'current_required':False})['product']
        self.assertEqual(old,first)
        result=self.service.call('gsd_product_handoff',self.transfer_args(first))
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'STALE_PRODUCT_VERSION')

    def test_I05_changed_input_rejected_before_transfer(self):
        p=self.register()['product'];args=self.transfer_args(p);args['input_objects']['INPUT.1']['text']='Иной вход'
        result=self.service.call('gsd_product_handoff',args)
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'STALE_PRODUCT_INPUT')

    def test_I05_caller_cannot_override_transport_status(self):
        p=self.register()['product'];args=self.transfer_args(p);args['header']['input_status']='validated'
        self.assertFalse(self.service.call('gsd_product_handoff',args)['ok'])

    def test_I05_registration_survives_process_store_reopen(self):
        p=self.register()['product'];other=Service()
        got=other.call('gsd_product_get',{'product_id':p['id']})
        self.assertTrue(got['ok']);self.assertEqual(got['result']['product'],p)

    def test_I05_ambiguous_or_invalid_status_rejected(self):
        for p in [{'status':True},{'status':0},{'status':''},{'status':'candidate','M':{'epistemic_status':'validated'}}]:
            with self.subTest(product=p),self.assertRaises(BridgeError):source_status(p)

    def test_I05_boolean_version_rejected(self):
        result=self.service.call('gsd_product_register',{'namespace':'x','logical_key':'x','product':{'x':1},
            'input_objects':{},'origin_component':'S','origin_ref':'E1','expected_version':True,'request_id':'x'})
        self.assertFalse(result['ok'])

    def test_I06_new_request_id_same_case_rejected(self):
        first=self.create();a=fixture('case_create.json');a['request_id']='new-request'
        result=self.service.call('gsd_case_create',a)
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'CASE_ALREADY_EXISTS')
        self.assertIn(first['run_id'],result['error']['message'])

    def test_I06_concurrent_create_cannot_duplicate_case(self):
        def create(i):
            a=fixture('case_create.json');a['request_id']='thread.'+str(i)
            return Service().call('gsd_case_create',a)
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(create,range(2)))
        self.assertEqual(sum(x['ok'] for x in results),1)
        self.assertEqual([x['error']['code'] for x in results if not x['ok']],['CASE_ALREADY_EXISTS'])

    def test_I06_closed_degraded_constructor_rejected(self):
        for status in ('closed','degraded'):
            a=fixture('case_create.json');a['case']['status']=status
            result=self.service.call('gsd_case_create',a)
            self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'RESTORE_REQUIRED')

    def spend_once(self,run,cost=3.5):
        return self.change(run,'commit',{'procedure_id':'BOOT.01','attempt_id':'ATTEMPT.ONE','status':'needs_data',
            'output_ids':[],'expected_revision':0,'postcondition_observed':'Отсутствует вход',
            'reason':'Нужно внешнее подтверждение','cost':cost},'spend-one')

    def new_host_args(self,run):
        a=fixture('case_create.json')
        return {'case':a['case'],'triggers':a['triggers'],'components':a['components'],
                'previous_run_id':run['run_id'],'expected_store_revision':run['store_revision'],
                'reason':'Отдельное явно разрешённое исследование','request_id':'host.new.1'}

    def test_I06_explicit_new_run_keeps_family_spend_and_stops_previous(self):
        first=self.spend_once(self.create());self.assertTrue(first['operation_accepted'])
        second=self.service.new_run_by_host(**self.new_host_args(first))
        self.assertNotEqual(second['run_id'],first['run_id'])
        self.assertEqual(second['spent_steps'],0);self.assertEqual(second['family_spent_steps'],1)
        self.assertEqual(second['family_spent_cost'],3.5)
        old=self.call('gsd_case_get',{'run_id':first['run_id']})
        self.assertEqual(old['state'],'partial');self.assertEqual(old['spent_steps'],1)

    def test_I06_same_new_run_authorization_is_idempotent(self):
        first=self.create();args=self.new_host_args(first)
        second=self.service.new_run_by_host(**args);again=self.service.new_run_by_host(**args)
        self.assertTrue(again['duplicate']);self.assertEqual(second['run_id'],again['run_id'])

    def test_I06_explicit_new_run_cannot_increase_budget(self):
        first=self.create();args=self.new_host_args(first);args['case']['contract']['budget']['step_limit']+=1
        with self.assertRaises(BridgeError) as exc:self.service.new_run_by_host(**args)
        self.assertEqual(exc.exception.code,'BUDGET_SCOPE_CHANGED')

    def test_I06_family_budget_enforced_across_two_runs(self):
        a=fixture('case_create.json');a['case']['contract']['budget']['step_limit']=3
        a['case']['contract']['budget']['reserve_steps']=1
        first=self.call('gsd_case_create',a);first=self.spend_once(first)
        args=self.new_host_args(first);args['case']=deepcopy(a['case'])
        second=self.service.new_run_by_host(**args);second=self.spend_once(second)
        self.assertEqual(second['family_spent_steps'],2)
        third_args=self.new_host_args(second);third_args['case']=deepcopy(a['case']);third_args['request_id']='host.new.2'
        with self.assertRaises(BridgeError) as exc:self.service.new_run_by_host(**third_args)
        self.assertEqual(exc.exception.code,'FAMILY_BUDGET_EXHAUSTED')

    def test_I06_restore_keeps_counters(self):
        run=self.spend_once(self.create());other=Service()
        got=other.call('gsd_case_get',{'run_id':run['run_id']})['result']
        self.assertEqual(got['spent_steps'],1);self.assertEqual(got['spent_cost'],3.5)
        self.assertEqual(got['family']['spent_steps'],1)

    def legacy(self,identifier='legacy-run',duplicate=False):
        a=fixture('case_create.json')
        engine=self.service.modules['engine'].ProcedureEngine(a['case'],a['triggers'])
        engine.commit('BOOT.01','legacy-attempt','needs_data',[],expected_revision=0,
            postcondition_observed='Проверка сохранения счётчика',reason='Нет входа',cost=3.5)
        engine.stop('Синтетический снимок остановленного запуска')
        snap=engine.snapshot()
        with self.service.store.transaction() as con:
            self.service.store.put(con,identifier,{'case':engine.case,'snapshot':snap,
                'engine_manifest':self.service.status()['engine_manifest_sha256']},2)
        return identifier

    def test_I06_legacy_state_cannot_be_bypassed_by_create(self):
        self.legacy()
        result=self.service.call('gsd_case_create',fixture('case_create.json'))
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'STATE_MIGRATION_REQUIRED')

    def test_I06_legacy_migration_preserves_exact_snapshot_and_counters(self):
        identifier=self.legacy();backup=self.tmp/'backup.sqlite3'
        with self.service.store.transaction() as con:_,old=self.service.store.get(con,identifier)
        plan=self.service.migrate_by_host(backup_path=str(backup))
        self.assertFalse(plan['applied']);self.assertFalse(backup.exists())
        applied=self.service.migrate_by_host(backup_path=str(backup),apply=True)
        self.assertTrue(applied['applied']);self.assertTrue(backup.is_file())
        with self.service.store.transaction() as con:_,new=self.service.store.get(con,identifier)
        self.assertEqual(old['snapshot'],new['snapshot'])
        got=self.call('gsd_case_get',{'run_id':identifier})
        self.assertEqual(got['spent_steps'],1);self.assertEqual(got['spent_cost'],3.5);self.assertEqual(got['state'],'partial')

    def test_I06_ambiguous_legacy_runs_require_explicit_reconciliation(self):
        self.legacy('legacy-a');self.legacy('legacy-b')
        with self.assertRaises(BridgeError) as exc:
            self.service.migrate_by_host(backup_path=str(self.tmp/'backup.sqlite3'),apply=True)
        self.assertEqual(exc.exception.code,'AMBIGUOUS_CASE_HISTORY')
        self.assertFalse((self.tmp/'backup.sqlite3').exists())

    def test_I06_family_record_tamper_rejected(self):
        run=self.create();family_id=run['budget_scope']
        con=sqlite3.connect(self.state/'state.sqlite3');con.execute('UPDATE records SET payload=? WHERE id=?',(b'{}',family_id));con.commit();con.close()
        result=self.service.call('gsd_case_get',{'run_id':run['run_id']})
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'STATE_INTEGRITY')

    def test_I07_upstream_manifest_still_exact(self):
        self.assertTrue(verify_tree(ROOT/'engine')['valid'])
        self.assertEqual(hashlib.sha256((ROOT/'engine/manifest.json').read_bytes()).hexdigest(),
                         'f2c9af730d0b2a4b06b451c16b15cd019c0b3359e2ee9236348dd7a3f6382738')

    def test_I07_invalid_top_level_and_nested_request_fail_without_provider(self):
        for name,args in [('gsd_status',[]),('gsd_execute',{'components':'G','request':[],'request_id':'bad'}),
                          ('gsd_execute',{'components':'G','request':{'generation':[]},'request_id':'bad2'})]:
            out=self.service.call(name,args)
            self.assertTrue(not out['ok'] or out['result'].get('effective_status')=='failed')
        self.assertFalse(self.service.call([],{})['ok'])

    def test_I07_no_false_original_adapter_or_effect_capability_claim(self):
        result=self.call('gsd_status',{})
        self.assertFalse(result['original_adapter_1_2_included'])
        self.assertEqual(result['external_effect_capability'],'unavailable_fail_closed')

    def test_I07_native_analysis_guard_cannot_be_disabled_by_configuration(self):
        dest=self.configure('hermes');path=dest/'plugins/gsd-integration/__init__.py'
        config_path=path.parent/'connection.json';cfg=load(config_path);cfg['enforce_analysis_only']=False;config_path.write_bytes(canonical(cfg))
        spec=importlib.util.spec_from_file_location('reject_disabled_guard',path);plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
        with self.assertRaises(ValueError):plugin._settings()

    def test_I07_cli_external_acceptance_uses_real_subprocess(self):
        _,receipt,_,_=self.external_fixture();path=self.tmp/'external-command.json';path.write_bytes(canonical({'receipt':receipt}))
        result=self.cli('host-command','external-commit','--json',str(path),'--host-control')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        out=json.loads(result.stdout)
        self.assertTrue(out['result']['operation_accepted']);self.assertEqual(out['result']['local_components'],['G'])


if __name__=='__main__':unittest.main(verbosity=2)
