import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bn_memory.store import Store
from bn_memory.broker import Broker
from bn_memory.knowledge import Knowledge

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name);self.project=r/'project';self.project.mkdir();self.cognee=r/'cognee';(self.cognee/'state').mkdir(parents=True);(self.cognee/'state/instance.json').write_text('{"instance_id":"unit-test"}')
        cfg={'namespace':{'owner_id':'test-owner','profile_id':'main'},'profile_home':str(r),'state_root':str(r/'memory'),'cognee_root':str(self.cognee),'cognee_enabled':True,'default_project':'a','projects':{'a':str(self.project),'b':str(r/'other')},'context_bytes':6000}
        s=Store(r/'memory',cfg);s.initialize();s.bind('parent');s.bind('other',project='b');s.bind('child','parent',subagent=True);self.b=Broker(cfg);self.k=Knowledge(self.b);(self.project/'source.md').write_text('Synthetic source: originals precede derived graph.\n')
    def tearDown(self):self.tmp.cleanup()
    def test_absent_executor_and_children_close_before_write(self):
        with self.assertRaises(PermissionError):self.k.ingest('parent',{'path':'source.md','request_id':'one'},None)
        with self.assertRaises(PermissionError):self.k.prepare('child',{'path':'source.md','request_id':'one'})
        self.assertEqual(self.k.docs('parent'),[])
    def test_exact_original_and_range_provenance(self):
        row,_=self.k.prepare('parent',{'path':'source.md','request_id':'one','length':10});m=json.loads(row['metadata']);self.assertFalse(m['full_source_processed']);self.assertEqual(m['length'],10);self.assertTrue(self.k._valid(row))
        Path(row['text_path']).write_text('tampered');self.assertFalse(self.k._valid(row))
    def test_foreign_scope_and_secret(self):
        row,_=self.k.prepare('parent',{'path':'source.md','request_id':'one'})
        with self.assertRaises(PermissionError):self.k._doc('other',row['id'])
        (self.project/'private.txt').write_text('api_key=synthetic-should-not-index')
        with self.assertRaises(ValueError):self.k.prepare('parent',{'path':'private.txt','request_id':'private'})
    def test_updated_primary_record_invalidates_derived(self):
        args={'content':'Version one','source_ref':'test:synthetic','kind':'note','request_id':'one','scope':'project'};record=self.b.store.record('parent',args);row,_=self.k.prepare('parent',{'record_id':record['id'],'request_id':'ingest'})
        self.assertTrue(self.k._valid(row));self.b.store.record('parent',{**args,'id':record['id'],'expected_revision':1,'request_id':'two','content':'Version two'});self.assertFalse(self.k._valid(row))
    def test_incomplete_worker_not_success(self):
        with patch.object(self.k,'worker',return_value={'result':{'status':'errored'}}):
            with self.assertRaises(RuntimeError):self.k.ingest('parent',{'path':'source.md','request_id':'one'},{'url':'unused','token':'unused'})
        self.assertEqual(self.k.docs('parent')[0]['status'],'partial')
    def test_unqualified_child_status_denied_parent_status_preserved(self):
        self.k.prepare('parent',{'path':'source.md','request_id':'one'})
        with self.assertRaisesRegex(PermissionError,'child_graph_dependency_filter_not_qualified'):
            self.k.manage('child',{'action':'status'},None)
        self.assertEqual(len(self.k.manage('parent',{'action':'status'},None)['sources']),1)
        with self.assertRaises(PermissionError):self.k.manage('child',{'action':'enrich'},None)
    def test_withdrawal_does_not_trust_dataset_wide_remember_items(self):
        row,_=self.k.prepare('parent',{'path':'source.md','request_id':'one'})
        with self.b.store.db() as c:c.execute("UPDATE knowledge_docs SET status='indexed',receipt=? WHERE id=?",(json.dumps({'result':{'items':[{'id':'target'},{'id':'unrelated'}]}}),row['id']))
        def worker(op,payload,runtime):
            if op=='resolve_ids':return {'data_ids':['verified-target']}
            self.assertEqual(op,'forget');self.assertEqual(payload['data_id'],'verified-target');return {'status':'success'}
        with patch.object(self.k,'worker',side_effect=worker) as mocked:
            result=self.k.manage('parent',{'action':'forget','doc_id':row['id']},{'url':'unused','token':'unused'})
        self.assertEqual(mocked.call_count,2);self.assertEqual(result['status'],'forgotten');self.assertTrue((self.k.artifacts/row['source_hash']).exists())
    def test_unaccepted_lesson_stops_before_processing(self):
        with patch.object(self.k,'worker') as worker:
            with self.assertRaisesRegex(PermissionError,'lesson_pipeline_not_accepted'):self.k.manage('parent',{'action':'lesson','record_id':'unread','request_id':'unexecuted'},{'url':'unused','token':'unused'})
        worker.assert_not_called()
    def test_lesson_provenance_duplicate_and_changed_input(self):
        self.k.config['cognee_lesson_enabled']=True
        source=self.b.store.record('parent',{'content':'Observed procedural source','source_ref':'evidence:test','kind':'source','request_id':'lesson-source','scope':'project'})
        args={'action':'lesson','record_id':source['id'],'request_id':'one-lesson','scope':'project'}
        result={'result':{'status':'completed','documents':['A model-derived procedural candidate.']}}
        with patch.object(self.k,'worker',return_value=result) as worker:
            first=self.k.manage('parent',args,{'url':'unused','token':'unused'})
            repeated=self.k.manage('parent',args,{'url':'unused','token':'unused'})
            self.assertEqual(worker.call_count,1);self.assertTrue(repeated['duplicate'])
            self.assertIn('-lesson-',worker.call_args.args[1]['dataset'])
        candidate=self.b.store.read('parent',first['result']['candidate_record_ids'][0]);self.assertEqual(candidate['kind'],'candidate');self.assertIn(source['content_hash'],candidate['source']);self.assertEqual(candidate['evidence_status'],'unreviewed')
        self.b.store.record('parent',{'id':source['id'],'expected_revision':1,'content':'Changed source','source_ref':'evidence:test','kind':'source','request_id':'changed','scope':'project'})
        with self.assertRaisesRegex(ValueError,'lesson_request_input_conflict'):self.k.manage('parent',args,{'url':'unused','token':'unused'})

if __name__=='__main__':unittest.main()
