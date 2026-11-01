import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bn_memory.store import Store
from bn_memory.plugin import Host
from bn_memory.broker import Broker

def allow_fixture_embeddings(config):
    from bn_memory.backend_policy import resource_hash
    config['backend_policy']={'version':1,'allow':{'embedding':{'operations':['query','document'],'resource_sha256':resource_hash(config,'embedding')}}}

class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name);(r/'project').mkdir()
        source=Path(__file__).parents[1]
        from hermes_constants import get_hermes_home
        self.config={'namespace':{'owner_id':'test-owner','profile_id':'main'},'profile_home':str(get_hermes_home()),'package_root':str(source),'state_root':str(r/'state'),'default_project':'p','projects':{'p':str(r/'project')},'host_key':str(r/'key'),'context_bytes':2000,
                     'tool_policy':{'version':1,'rules':[{'id':'memory-write','tool':'mcp__context__memory_record','effect':'write_local','roles':['parent'],'arguments_schema':{'type':'object'}}]}}
        (r/'key').write_bytes(os.urandom(32));self.path=r/'config.json';self.path.write_text(json.dumps(self.config));Store(r/'state',self.config).initialize();self.host=Host(self.path)
    def tearDown(self):self.host.close();self.tmp.cleanup()
    def test_final_context_and_missing_context_block(self):
        self.host.before_turn(session_id='parent',user_message='Question',turn_id='t')
        request={'messages':[{'role':'user','content':'Question'}]};changed=self.host.request(request,session_id='parent',turn_id='t',api_request_id='test-api')['request']
        self.assertTrue(self.host.model_control({'request':changed},session_id='parent',turn_id='t',api_request_id='test-api').allow)
        self.assertFalse(self.host.model_control({'request':request},session_id='parent',turn_id='t',api_request_id='test-api').allow)
        self.host.store.path.rename(self.host.store.path.with_suffix('.off'))
        self.assertFalse(self.host.model_control({'request':changed},session_id='parent',turn_id='t',api_request_id='test-api').allow)
    def test_signed_tool_and_child_restriction(self):
        self.host.before_turn(session_id='parent',user_message='Question',turn_id='t');self.host.child_start(parent_session_id='parent',child_session_id='child')
        name='mcp__context__memory_record';args={'content':'x'}
        from agent.tool_attempt import tool_attempt_scope
        identity={'session_id':'parent','turn_id':'t','tool_call_id':'call','api_request_id':'test-api'}
        with tool_attempt_scope(name,identity,final_boundary='registry'):
            signed=self.host.tool_request(name,args,session_id='parent')['args']
            self.assertTrue(self.host.tool_control({'tool_name':name,'args':signed},boundary='registry',**identity).allow)
            self.assertFalse(self.host.tool_control({'tool_name':name,'args':signed},session_id='child').allow)
            signed['content']='tampered';self.assertFalse(self.host.tool_control({'tool_name':name,'args':signed},boundary='registry',**identity).allow)
    def test_optional_backends_fail_with_primary_results(self):
        self.host.store.bind('parent');self.host.store.record('parent',{'content':'Atlas originals SQLite','source_ref':'test:synthetic','kind':'note','request_id':'one','scope':'project'})
        with patch.object(self.host.broker,'worker',side_effect=RuntimeError('unavailable')),patch.object(self.host.broker,'embedding',side_effect=RuntimeError('unavailable')):
            r=self.host.broker.recall('parent',{'query':'Atlas','mode':'hybrid'});self.assertEqual(len(r['records']),1);self.assertTrue(all(x['status']=='unavailable' for x in r['derived'].values()))
    def test_foreign_pending_queue_does_not_starve_current_scope(self):
        self.host.store.bind('foreign');self.host.store.bind('parent')
        args={'content':'Foreign task','source_ref':'test:synthetic','kind':'note','request_id':'one','scope':'task'}
        self.host.store.record('foreign',args)
        own=self.host.store.record('parent',{**args,'content':'Own task','request_id':'two'})
        with patch.object(self.host.broker,'worker',return_value={'status':'indexed'}),patch.object(self.host.broker,'embedding',return_value=[0.0]*1024):
            r=self.host.broker.sync('parent',3)
        self.assertEqual(len(r['results']),3);self.assertTrue(all(x['id']==own['id'] for x in r['results']))
    def test_concurrent_embedding_budget_is_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        self.host.broker.config.update({'embedding_daily_bytes':300,'embedding_url':'http://unused','voyage_key_file':'unused'})
        allow_fixture_embeddings(self.host.broker.config)
        def call(text):
            try:self.host.broker.embedding(text,'query');return 'reserved'
            except RuntimeError:return 'blocked'
        with patch('bn_memory.broker.http',return_value={'data':[{'index':0,'embedding':[1.0]+[0.0]*1023}]}),ThreadPoolExecutor(2) as pool:results=list(pool.map(call,['one','two']))
        self.assertEqual(sorted(results),['blocked','reserved'])
        with self.host.store.db() as c:self.assertLessEqual(c.execute('SELECT bytes FROM budget').fetchone()[0],300)

if __name__=='__main__':unittest.main()

class ReasoningRecoveryTests(HostTests):
    def test_incomplete_fallback_preserves_configured_effort_and_context(self):
        self.host.approved_effort=lambda model: "xhigh"
        self.host.before_turn(session_id='parent',user_message='Synthetic question',turn_id='t')
        original={'model':'gpt-6.1-sol','input':[{'role':'user','content':'Synthetic question'}],'reasoning':{'effort':'none'},'max_output_tokens':32768}
        changed=self.host.request(original,session_id='parent',turn_id='t',api_request_id='test-api')['request']
        self.assertEqual(original['reasoning']['effort'],'none')
        self.assertEqual(changed['reasoning']['effort'],'xhigh')
        self.assertEqual(changed['max_output_tokens'],32768)
        self.assertTrue(self.host.model_control({'request':changed},session_id='parent',turn_id='t',api_request_id='test-api').allow)
        changed['reasoning']['effort']='none'
        self.assertFalse(self.host.model_control({'request':changed},session_id='parent',turn_id='t',api_request_id='test-api').allow)
    def test_other_model_is_not_changed(self):
        self.host.before_turn(session_id='parent',user_message='Synthetic question',turn_id='t')
        original={'model':'gpt-6-sol','input':[{'role':'user','content':'Synthetic question'}],'reasoning':{'effort':'none'}}
        changed=self.host.request(original,session_id='parent',turn_id='t',api_request_id='test-api')['request']
        self.assertEqual(changed['reasoning']['effort'],'none')

class ObservationEmbeddingTests(HostTests):
    def test_removed_daily_cap_retains_charge_and_secret_guard(self):
        import time
        cfg=self.host.broker.config;cfg.update(embedding_daily_bytes=None,embedding_url='http://unused',voyage_key_file='unused')
        allow_fixture_embeddings(cfg)
        day=time.strftime('%Y-%m-%d',time.gmtime())
        with self.host.store.db() as db:db.execute('INSERT INTO budget VALUES(?,?)',(day,2000000))
        with patch('bn_memory.broker.http',return_value={'data':[{'index':0,'embedding':[1.0]+[0.0]*1023}]}):
            self.host.broker.embedding('Synthetic index query','query')
        with self.host.store.db() as db:self.assertGreater(db.execute('SELECT bytes FROM budget').fetchone()[0],2000000)
        with self.assertRaises(ValueError):self.host.broker.embedding('api_key=sk-abcdefghijklmnopqrstuv','query')
