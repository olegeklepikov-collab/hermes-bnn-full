"""Regression checks for the concrete access, Unicode and public-API findings."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,unittest
from unittest.mock import patch

def suite(cfg,api):
    root=Path(__file__).resolve().parents[1]
    class ExtensionBoundaries(unittest.TestCase):
        def test_tinyfish_MCP_jobs_and_stateful_writes_are_distinct(self):
            self.assertEqual(api.effect('tinyfish','start_deep_research'),'job')
            for name in ['get_deep_research','list_deep_research','plan_dataset','get_dataset','get_dataset_rows','list_datasets']:
                self.assertEqual(api.effect('tinyfish',name),'read')
            for name in ['create_dataset','populate_dataset','delete_dataset','run_web_automation','run_web_automation_async','create_monitor']:
                self.assertEqual(api.effect('tinyfish',name),'write')
        def test_tinyfish_MCP_raw_browser_wallet_and_unknown_methods_closed(self):
            for name in ['create_browser_session','list_browser_sessions','close_browser_session','top_up_wallet','unknown_new_tool']:
                self.assertEqual(api.effect('tinyfish',name),'blocked')
        def test_public_data_uses_production_get_only(self):
            cat=api.read_catalog(cfg)['services']['datacite']['methods']
            self.assertGreaterEqual(len(cat),16)
            for method in cat.values():
                self.assertEqual(method['effect'],'read')
                self.assertEqual(method['api_request']['method'],'GET')
                self.assertEqual(method['api_request']['base'],'https://api.datacite.org')
        def test_tinyfish_browser_goal_is_not_a_read_or_unguarded_job(self):
            for method in api.read_catalog(cfg)['services']['tinyfish-api']['methods'].values():
                path=method['api_request']['path']
                if path in ['/v1/automation/run','/v1/automation/run-async','/v1/automation/run-batch']:
                    self.assertEqual(method['effect'],'write')
        def test_tinyfish_payments_vault_and_unconfined_cdp_closed(self):
            for method in api.read_catalog(cfg)['services']['tinyfish-api']['methods'].values():
                path=method['api_request']['path']
                if '/vault' in path or '/wallet/top-up' in path or 'browser' in method['api_request']['base']:
                    self.assertEqual(method['effect'],'blocked')
        def test_unadapted_streams_and_uploads_fail_closed(self):
            for sn in ['tinyfish-api','elicit-api']:
                for method in api.read_catalog(cfg)['services'][sn]['methods'].values():
                    path=method['api_request']['path']
                    if '/events' in path or 'run-sse' in path or method['unsupported']:
                        self.assertEqual(method['effect'],'blocked')
        def test_missing_access_fails_before_transport(self):
            reg=json.loads(Path(cfg['service_integration']['registry_file']).read_text())
            for entry in reg['services']:
                if entry.get('connection_hold'):
                    with self.subTest(service=entry['service']),self.assertRaisesRegex(PermissionError,'connection_not_ready'):
                        api.verify_entry(cfg,entry['service'])
        def test_synapse_has_no_account_permission_or_mutation_routes(self):
            for method in api.read_catalog(cfg)['services']['synapse']['methods'].values():
                path=method['api_request']['path']
                self.assertNotIn('/auth/',path);self.assertNotIn('/acl',path)
                if method['effect']!='blocked':self.assertIn(method['effect'],{'read','job'})
        def test_elicit_research_is_parent_job_not_child_read(self):
            for method in api.read_catalog(cfg)['services']['elicit-api']['methods'].values():
                if method['api_request']['path'] in ['/sessions/reports','/sessions/systematic-reviews','/sessions/agents'] and method['api_request']['method']=='POST':
                    self.assertEqual(method['effect'],'job')
        def test_dense_models_point_to_present_own_pinned_snapshots(self):
            p=root/'Services/software/ASReview/config';models=json.loads((p/'models.json').read_text());snapshots=json.loads((p/'model-snapshots.json').read_text())
            for model,repo in [('elas_l2','intfloat/multilingual-e5-large'),('elas_h3','mixedbread-ai/mxbai-embed-large-v1')]:
                path=Path(models[model]['value']['feature_extractor_param']['model_name'])
                self.assertEqual(path,Path(snapshots[repo]['path']));self.assertTrue(path.is_relative_to(root));self.assertTrue((path/'model.safetensors').is_file())
        def test_distinct_cyrillic_records_do_not_disappear_as_duplicates(self):
            spec=importlib.util.spec_from_file_location('unicode_dedup',root/'Services/software/ASReview/unicode_groups.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            records=[SimpleNamespace(record_id=i,title=t,abstract=a) for i,(t,a) in enumerate([
                ('Обратная связь','Обучение математике'),('Астрономия','Далёкие галактики'),
                ('ОБРАТНАЯ СВЯЗЬ!','Обучение математике'),('',''),('','')])]
            self.assertEqual(m.record_groups(records),[(0,0),(1,1),(0,2),(3,3),(4,4)])
        def test_public_transport_does_not_require_or_emit_bearer_key(self):
            from bn_memory.service_transport import rest_call
            class Response:
                status_code=200;headers={'content-type':'application/json'}
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def iter_content(self,n):yield b'{"data":[]}'
            class Client:
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def request(self,*args,**kwargs):
                    if 'Authorization' in kwargs['headers']:raise AssertionError('public request leaked an auth header')
                    return Response()
            method={'api_request':{'method':'GET','base':'https://api.datacite.org','path':'/dois','parameters':{}}}
            with patch('requests.Session',Client):value=rest_call({'service':'datacite'},method,{}, {'headers':{},'env':{}})
            self.assertFalse(value['isError']);self.assertEqual(value['data'],{'data':[]})
        def test_public_transport_still_rejects_changed_host(self):
            from bn_memory.service_transport import rest_call
            method={'api_request':{'method':'GET','base':'https://example.com','path':'/dois','parameters':{}}}
            with self.assertRaisesRegex(PermissionError,'endpoint_pin_mismatch'):
                rest_call({'service':'datacite'},method,{}, {'headers':{},'env':{}})
    return unittest.defaultTestLoader.loadTestsFromTestCase(ExtensionBoundaries)
