"""Локальные проверки. Модели, настоящий Hermes, Telegram и IDE не вызываются."""
from __future__ import annotations
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from gsd_bridge.common import BridgeError, canonical, digest, load, read_json, verify_tree
from gsd_bridge.service import Service, TOOLS, MODES
from gsd_bridge.mcp import MCPServer, PROTOCOL
from adapters.host_guard import GuardedDispatcher, BlockedAction, request_digest

def fixture(path):
    return load(ROOT/'examples'/path)

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gsd-integration-check-')
        self.tmp=Path(self.temp.name);self.state=self.tmp/'state';self.state.mkdir(mode=0o700)
        self.key=self.tmp/'trust.key';self.key.write_bytes(os.urandom(32));self.key.chmod(0o600)
        self.env=patch.dict(os.environ,{'GSD_STATE_DIR':str(self.state),'GSD_TRUST_KEY_FILE':str(self.key),'GSD_PROVIDER_CONFIG':'','GSD_HOST_POLICY':''})
        self.env.start();self.service=Service()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def call(self,name,args):
        value=self.service.call(name,args);self.assertTrue(value['ok'],value)
        return value['result']
    def execution(self,path='modes/GSD.json'):
        return self.call('gsd_execute',fixture(path))
    def create(self):
        return self.call('gsd_case_create',fixture('case_create.json'))
    def change(self,run,op,payload,request_id='change-1'):
        return self.call('gsd_case_change',{'run_id':run['run_id'],'request_id':request_id,
             'expected_store_revision':run['store_revision'],'operation':op,'payload':payload})
    def cli(self,*args,data=None):
        return subprocess.run([sys.executable,'-I','-B',str(ROOT/'gsd.py'),*args],
            input=data,text=True,encoding='utf-8',capture_output=True,timeout=45,env=dict(os.environ))
    def configure(self,target):
        dest=self.tmp/target
        p=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/configure.py'),'--target',target,'--output',str(dest),
            '--python',sys.executable,'--state-dir',str(self.state),'--key-file',str(self.key)],capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        return dest
    def provider(self,body):
        exe=self.tmp/'fixture_provider.py';exe.write_text(body,encoding='utf-8')
        cfg=self.tmp/'provider.json';cfg.write_text(json.dumps({'argv':[sys.executable,str(exe)],'provider_id':'synthetic-fixture','timeout_seconds':2}))
        os.environ['GSD_PROVIDER_CONFIG']=str(cfg)
        return cfg

    def test_original_manifest_intact(self):
        v=verify_tree(ROOT/'engine');self.assertTrue(v['valid'],v);self.assertFalse(v['authenticity_proven'])
    def test_status_distinguishes_semantics(self):
        v=self.call('gsd_status',{});self.assertEqual(v['integration_version'],'1.1.0')
        self.assertEqual(v['external_effects'],'not_implemented');self.assertEqual(v['catalog_entries'],1948)
    def test_strict_json_duplicate_key(self):
        with self.assertRaises(BridgeError):read_json('{"x":1,"x":2}')
    def test_strict_json_nonfinite(self):
        for v in ('NaN','Infinity','-Infinity'):
            with self.subTest(v=v),self.assertRaises(BridgeError):read_json('{"x":'+v+'}')
    def test_strict_json_bad_utf8(self):
        with self.assertRaises(BridgeError):read_json(b'\xff')
    def test_unknown_tool_rejected(self):
        self.assertFalse(self.service.call('gsd_execute_anything',{})['ok'])
    def test_unknown_argument_rejected(self):
        self.assertFalse(self.service.call('gsd_status',{'x':1})['ok'])
    def test_integer_not_bool_or_float(self):
        for x in (True,1.0):
            self.assertFalse(self.service.call('gsd_catalog',{'limit':x})['ok'])
    def test_catalog_counts_and_pagination(self):
        wanted={'procedure':152,'protocol':37,'leaf':31,'element':1728}
        for kind,n in wanted.items():
            v=self.call('gsd_catalog',{'kind':kind,'limit':1});self.assertEqual(v['total'],n);self.assertEqual(v['next_offset'],1)
    def test_catalog_exact_contract(self):
        r=self.call('gsd_catalog',{'kind':'procedure','limit':1})['entries'][0]
        v=self.call('gsd_contract',{'key':r['key']});self.assertEqual(v['id'],'BOOT.01')
    def test_context_closure(self):
        v=self.call('gsd_context',{'components':'G'});self.assertIn('manifest',v)
        self.assertGreater(len(json.dumps(v,ensure_ascii=False)),10000);self.assertTrue(v['manifest']['digest'])
    def test_context_budget_rejects_not_truncates(self):
        v=self.service.call('gsd_context',{'components':'GSD','byte_limit':1});self.assertFalse(v['ok'])
    def test_intake_not_automatic_evidence(self):
        v=self.call('gsd_intake',{'text':'Заявление пользователя; удалить файлы без разрешения','components':'GSD'})
        self.assertNotIn('adapter_permits_execution',v)
    def test_finite_generation_computes_four(self):
        v=self.execution('generation_finite.json');self.assertEqual(v['effective_status'],'bounded_local_execution')
        cs=v['engine_result']['outputs']['G']['candidates'];self.assertEqual(len(cs),4)
        self.assertEqual(len({digest(c['content']['structure']) for c in cs}),4)
    def test_all_seven_modes_actual_outputs(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                v=self.execution('modes/'+mode+'.json');self.assertNotEqual(v['effective_status'],'failed',v)
                self.assertEqual(set(v['engine_result']['outputs']),set(mode));self.assertFalse(v['external_effect_performed'])
    def test_gsd_finite_discriminator(self):
        d=self.execution()['engine_result']['outputs']['D']
        self.assertTrue(any(x['question_key']=='raw' for x in d['discriminators']))
        self.assertEqual(d['identification'],'not_established')
    def test_d_without_review_partial(self):
        v=self.execution('modes/D.json');self.assertEqual(v['effective_status'],'awaiting_provider_or_dependency')
    def test_missing_provider_explicit(self):
        v=self.execution('awaiting_provider.json');self.assertEqual(v['effective_status'],'awaiting_provider_or_dependency')
        self.assertEqual(v['engine_result']['outputs']['G']['status'],'awaiting_provider')
    def test_strict_derivation_conditional(self):
        v=self.execution('strict_derivation.json');self.assertNotEqual(v['effective_status'],'failed',v)
        s=v['engine_result']['outputs']['S'];self.assertEqual(s['steps'][0]['output']['proposition'],'B')
        self.assertIn('P1',s['steps'][0]['output']['conditional_on'])
    def test_supplied_is_not_claimed_generated(self):
        v=self.execution('modes/G.json');s=json.dumps(v,ensure_ascii=False)
        self.assertIn('candidate_received_not_generated_here',s)
    def test_reused_candidates_reach_s(self):
        a=fixture('modes/GS.json');known=copy.deepcopy(a['request']['generation']['supplied_candidates'])
        a['request']['generation']['known_candidates']=known
        v=self.call('gsd_execute',a);self.assertNotEqual(v['effective_status'],'failed',v)
        self.assertEqual(len(v['engine_result']['outputs']['S']['rows']),2)
    def test_execute_idempotent(self):
        v=self.execution();again=self.execution();self.assertTrue(again['duplicate'])
        self.assertEqual(v['engine_result'],again['engine_result'])
    def test_execute_idempotency_collision(self):
        self.execution();a=fixture('modes/GSD.json');a['request']['question']='Иной вопрос'
        v=self.service.call('gsd_execute',a);self.assertFalse(v['ok']);self.assertEqual(v['error']['code'],'IDEMPOTENCY_CONFLICT')
    def test_unknown_outcome_not_reexecuted(self):
        a=fixture('modes/GSD.json');fp=self.service._request_digest([a['components'],a['request']])
        with self.service.store.transaction() as con:
            self.service.store.remember(con,'triad',a['request_id'],fp,{'effective_status':'in_progress_or_outcome_unknown','automatic_retry_forbidden':True})
        v=self.call('gsd_execute',a);self.assertEqual(v['effective_status'],'in_progress_or_outcome_unknown');self.assertTrue(v['duplicate'])
    def test_local_budget_exhaustion(self):
        a=fixture('modes/GSD.json');a['request']['execution_budget']={'step_limit':2,'reserve_steps':1}
        self.assertEqual(self.call('gsd_execute',a)['effective_status'],'failed')
    def test_scope_substitution_rejected(self):
        a=fixture('modes/GSD.json');a['request']['generation']['scope']='other'
        v=self.call('gsd_execute',a);self.assertEqual(v['effective_status'],'failed');self.assertEqual(v['error']['code'],'SCOPE_MISMATCH')
    def test_case_schema_valid(self):
        v=self.call('gsd_validate_case',{'case':fixture('case_create.json')['case']});self.assertTrue(v['valid_contract'])
    def test_case_creation_duplicate(self):
        a=self.create();b=self.create();self.assertEqual(a['run_id'],b['run_id']);self.assertTrue(b['duplicate'])
    def test_case_next_advances_store_not_case_revision(self):
        a=self.create();b=self.call('gsd_case_next',{'run_id':a['run_id']})
        self.assertEqual(b['store_revision'],1);self.assertEqual(b['case_revision'],0);self.assertEqual(b['next']['procedure']['id'],'BOOT.01')
    def test_case_forged_commit_rejected(self):
        a=self.create();v=self.change(a,'commit',{'procedure_id':'BOOT.01','attempt_id':'fake','status':'pass','output_ids':['NONEXISTENT'],
            'expected_revision':0,'postcondition_observed':'Исполнено'})
        self.assertFalse(v['operation_accepted']);self.assertEqual(v['spent_steps'],0)
    def test_case_stale_store_revision(self):
        a=self.create();self.call('gsd_case_next',{'run_id':a['run_id']})
        v=self.service.call('gsd_case_change',{'run_id':a['run_id'],'request_id':'stop','expected_store_revision':0,'operation':'stop','payload':{'reason':'stop'}})
        self.assertEqual(v['error']['code'],'STALE_REVISION')
    def test_case_agent_cannot_raise_budget(self):
        a=self.create();c=fixture('case_create.json')['case'];c['revision']=1;c['contract']['budget']['step_limit']+=1
        v=self.change(a,'update',{'case':c,'expected_case_revision':0});self.assertFalse(v['operation_accepted'])
        self.assertEqual(v['error']['code'],'HOST_CONTROL_REQUIRED')
    def test_case_stop_persists_and_host_resume(self):
        a=self.create();b=self.change(a,'stop',{'reason':'Явная остановка оператора'})
        self.assertTrue(b['operation_accepted']);self.assertNotEqual(b['state'],'active')
        self.assertNotIn('gsd_case_resume',TOOLS)
        c=self.service.resume_by_host(a['run_id'],b['store_revision'],'Ресурс подтверждён оператором');self.assertEqual(c['state'],'active')
    def test_case_state_tampering_rejected(self):
        a=self.create()
        con=sqlite3.connect(self.state/'state.sqlite3');con.execute("UPDATE records SET payload=? WHERE id=?",(b'{}',a['run_id']));con.commit();con.close()
        v=self.service.call('gsd_case_get',{'run_id':a['run_id']});self.assertFalse(v['ok']);self.assertEqual(v['error']['code'],'STATE_INTEGRITY')
    def test_case_wrong_key_rejected(self):
        a=self.create();self.key.write_bytes(os.urandom(32));other=Service()
        v=other.call('gsd_case_get',{'run_id':a['run_id']});self.assertEqual(v['error']['code'],'STATE_INTEGRITY')
    def test_case_action_use_not_created(self):
        a=fixture('case_create.json');a['case']['contract']['intended_use']='action'
        self.assertFalse(self.service.call('gsd_case_create',a)['ok'])
    def test_case_isolated_state_has_no_record(self):
        a=self.create();new=self.tmp/'other';new.mkdir(mode=0o700);os.environ['GSD_STATE_DIR']=str(new)
        v=Service().call('gsd_case_get',{'run_id':a['run_id']});self.assertEqual(v['error']['code'],'NOT_FOUND')
    def test_missing_key_not_automatically_replaced(self):
        self.key.unlink();v=self.service.call('gsd_case_create',fixture('case_create.json'))
        self.assertFalse(v['ok']);self.assertFalse(self.key.exists())
    def test_hand_off_missing_contract_rejected(self):
        self.assertFalse(self.service.call('gsd_handoff_validate',{'message':{'id':'x'}})['ok'])
    def test_provider_command_real_process_synthetic_output(self):
        candidates=fixture('modes/G.json')['request']['generation']['supplied_candidates']
        self.provider('import sys,json\np=json.load(sys.stdin)\nassert p["contract"]=="gsd.generation-provider/1"\nprint('+repr(json.dumps({'candidates':candidates},ensure_ascii=False))+')\n')
        v=self.execution('awaiting_provider.json');self.assertEqual(v['effective_status'],'bounded_local_execution',v)
        self.assertTrue(v['provider_receipt']['process_invoked']);self.assertEqual(v['provider_receipt']['provider_id'],'synthetic-fixture')
        self.assertEqual(v['semantic_acceptance'],'not_established')
    def test_provider_nonzero_fails(self):
        self.provider('raise SystemExit(3)\n');v=self.execution('awaiting_provider.json');self.assertEqual(v['effective_status'],'failed')
    def test_provider_extra_output_field_rejected(self):
        self.provider('print(\'{"candidates":[],"approved":true}\')\n');v=self.execution('awaiting_provider.json')
        self.assertEqual(v['effective_status'],'failed')
    def test_provider_timeout_has_no_auto_retry(self):
        cfg=self.provider('import time\ntime.sleep(10)\n');c=json.loads(cfg.read_text());c['timeout_seconds']=0.04;cfg.write_text(json.dumps(c))
        v=self.execution('awaiting_provider.json');self.assertEqual(v['effective_status'],'failed');self.assertTrue(v['automatic_retry_forbidden'])
        self.assertTrue(self.execution('awaiting_provider.json')['duplicate'])
    def test_guard_denies_before_file_effect(self):
        marker=self.tmp/'effect'
        fn=GuardedDispatcher(lambda *_:{'allow':False},lambda *_:marker.write_text('effect'))
        with self.assertRaises(BlockedAction):fn('write',{'target':str(marker)})
        self.assertFalse(marker.exists())
    def test_guard_error_denies_before_file_effect(self):
        marker=self.tmp/'effect'
        def fail(*_):raise RuntimeError('unavailable')
        fn=GuardedDispatcher(fail,lambda *_:marker.write_text('effect'))
        with self.assertRaises(BlockedAction):fn('write',{})
        self.assertFalse(marker.exists())
    def test_guard_exact_arguments_required(self):
        called=[];fn=GuardedDispatcher(lambda *_:{'allow':True,'request_digest':'wrong'},lambda *a:called.append(a))
        with self.assertRaises(BlockedAction):fn('write',{'x':1})
        self.assertFalse(called)
    def test_guard_authorized_dispatch_and_input_freezing(self):
        seen=[]
        def authorize(n,a):
            h=request_digest(n,a);a['x']=999
            return {'allow':True,'request_digest':h}
        GuardedDispatcher(authorize,lambda n,a:seen.append(a))('write',{'x':1})
        self.assertEqual(seen,[{'x':1}])
    def test_mcp_requires_handshake(self):
        s=MCPServer();v=s.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        self.assertIn('error',v)
    def test_mcp_actual_subprocess_lifecycle_tools_resources(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'local-fixture','version':'1'}}},
          {'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'},
          {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'gsd_status','arguments':{}}},
          {'jsonrpc':'2.0','id':4,'method':'resources/read','params':{'uri':'gsd://integration/guide'}},
          {'jsonrpc':'2.0','id':5,'method':'prompts/get','params':{'name':'gsd-workflow'}}]
        p=self.cli('mcp',data='\n'.join(json.dumps(x) for x in messages)+'\n');self.assertEqual(p.returncode,0,p.stderr)
        replies=[json.loads(x) for x in p.stdout.splitlines()];self.assertEqual(len(replies),5)
        self.assertEqual(replies[0]['result']['protocolVersion'],PROTOCOL)
        self.assertEqual(len(replies[1]['result']['tools']),16);self.assertTrue(replies[2]['result']['structuredContent']['ok'])
        self.assertIn('contents',replies[3]['result']);self.assertIn('messages',replies[4]['result'])
    def test_mcp_unknown_tool_reports_error(self):
        s=MCPServer();s.ready=True
        v=s.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'bad','arguments':{}}})
        self.assertTrue(v['result']['isError'])
    def test_cli_success_and_invalid_json_exit(self):
        good=self.cli('status');self.assertEqual(good.returncode,0,good.stderr);self.assertTrue(json.loads(good.stdout)['ok'])
        bad=self.cli('call','gsd_status','--json','-',data='{"a":1,"a":2}')
        self.assertEqual(bad.returncode,2);self.assertEqual(json.loads(bad.stdout)['error']['code'],'INVALID_JSON')
    def test_generated_settings_all_targets(self):
        for target in ['hermes','vscode','cursor','claude','codex','generic']:
            with self.subTest(target=target):
                dest=self.configure(target);receipt=json.loads((dest/'configuration_receipt.json').read_text())
                self.assertFalse(receipt['active_host_modified']);self.assertTrue((dest/'AGENTS.gsd.md').is_file())
                if target=='codex':
                    import tomllib
                    cfg=tomllib.loads((dest/'config.fragment.toml').read_text());self.assertIn('gsd',cfg['mcp_servers'])
                elif target=='vscode':self.assertIn('servers',json.loads((dest/'mcp.json').read_text()))
                elif target=='hermes':self.assertTrue((dest/'plugins/gsd-integration/connection.json').is_file())
                else:self.assertIn('mcpServers',json.loads((dest/('.mcp.json' if target=='claude' else 'mcp.json')).read_text()))
    def test_configuration_refuses_overwrite(self):
        self.configure('generic')
        p=subprocess.run([sys.executable,str(ROOT/'scripts/configure.py'),'--target','generic','--output',str(self.tmp/'generic'),
             '--state-dir',str(self.state),'--key-file',str(self.key)],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(p.returncode,0)
    def test_hermes_contract_registration_and_actual_handler(self):
        # Подставной PluginContext, НЕ запуск настоящего Hermes.
        dest=self.configure('hermes');path=dest/'plugins/gsd-integration/__init__.py'
        spec=importlib.util.spec_from_file_location('fixture_gsd_hermes',path);plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
        class Context:
            def __init__(self):self.tools={};self.hooks={};self.skills=[];self.commands={}
            def register_tool(self,**kw):self.tools[kw['name']]=kw
            def register_hook(self,name,fn):self.hooks[name]=fn
            def register_skill(self,*a):self.skills.append(a)
            def register_command(self,name,fn,**kw):self.commands[name]=fn
        ctx=Context();plugin.register(ctx);self.assertEqual(len(ctx.tools),16);self.assertEqual(len(ctx.skills),8)
        self.assertTrue(json.loads(ctx.tools['gsd_status']['handler']({}))['ok'])
        self.assertEqual(ctx.hooks['pre_tool_call']('write_file',{})['action'],'block')
        self.assertIsNone(ctx.hooks['pre_tool_call']('gsd_status',{}))
        self.assertIsNone(ctx.hooks['pre_tool_call']('skills_list',{}))
        (path.parent/'connection.json').unlink()
        self.assertEqual(ctx.hooks['pre_tool_call']('gsd_status',{})['action'],'block')
    def test_case_actual_boot_artifact_and_commit(self):
        a=self.create();n=self.call('gsd_case_next',{'run_id':a['run_id']})
        original_check=verify_tree(ROOT/'engine');self.assertTrue(original_check['valid'])
        case=self.call('gsd_case_get',{'run_id':a['run_id']})['case'];case['revision']+=1
        case['artifacts'].append({'id':'BOOT.OUT.1','version':1,'kind':'Запись комплектации','context_id':case['contexts'][0]['id'],
            'summary':json.dumps({'engine_release':'3.0.3','manifest_verified':original_check['valid'],'checked_files':original_check['checked_files']},ensure_ascii=False),
            'claim_ids':[],'evidence_ids':[],'limitations':['Проверена целостность комплекта, не предметные рассуждения'],
            'input_fingerprint':n['next']['input_fingerprint'],'semantic_result_refs':[],'accepted_limitations_by':[]})
        u=self.change(n,'update',{'case':case,'expected_case_revision':0},'boot-update')
        self.assertTrue(u['operation_accepted'],u)
        c=self.change(u,'commit',{'procedure_id':'BOOT.01','attempt_id':'BOOT.ATTEMPT.1','status':'pass','output_ids':['BOOT.OUT.1'],
            'expected_revision':1,'postcondition_observed':'Состав соответствует исходному манифесту; версия поставки 3.0.3.'},'boot-commit')
        self.assertTrue(c['operation_accepted'],c);self.assertEqual(c['spent_steps'],1)
        saved=self.call('gsd_case_get',{'run_id':a['run_id']})
        self.assertEqual(saved['case']['procedure_runs'][0]['output_ids'],['BOOT.OUT.1'])

    def test_closure_requires_actual_criterion_record(self):
        a=self.create();r=self.change(a,'close',{'criterion_record':'invented'})
        self.assertFalse(r['operation_accepted']);self.assertEqual(r['error']['code'],'CLOSURE_RECORD_REQUIRED')

    def test_export_context_full_file(self):
        out=self.tmp/'export'
        p=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/export_context.py'),'--components','G','--output',str(out)],
              capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        import hashlib
        raw=(out/'context.md').read_bytes();receipt=json.loads((out/'receipt.json').read_text())
        self.assertEqual(receipt['bytes'],len(raw));self.assertEqual(receipt['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertFalse(receipt['model_delivery_verified'])

    def test_mcp_all_resources_readable(self):
        from gsd_bridge.mcp import RESOURCES
        server=MCPServer();server.ready=True
        for uri in RESOURCES:
            response=server.handle({'jsonrpc':'2.0','id':1,'method':'resources/read','params':{'uri':uri}})
            self.assertIn('result',response,response);self.assertTrue(response['result']['contents'][0]['text'])

    def test_tools_schema_single_source(self):
        v=load(ROOT/'contracts/tools.json');native=load(ROOT/'adapters/hermes/schemas.json')
        # Разные внешние оболочки, одна схема входа.
        for item in native:
            self.assertEqual(item['parameters'],TOOLS[item['name']][1])
        self.assertEqual(len(v['tools']),16)
        self.assertEqual(v['tools'],native)
    def test_skills_frontmatter_minimal_contract(self):
        paths=list((ROOT/'skills').glob('*/SKILL.md'));self.assertEqual(len(paths),8)
        for p in paths:
            text=p.read_text();self.assertTrue(text.startswith('---\nname: '+p.parent.name+'\n'))
            self.assertIn('\ndescription: ',text);self.assertLess(len(text.splitlines()),500)

if __name__=='__main__':unittest.main(verbosity=2)
