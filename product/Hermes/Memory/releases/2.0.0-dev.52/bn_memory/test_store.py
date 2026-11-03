import json
import tempfile
import unittest
from pathlib import Path
from bn_memory.store import Store,canonical

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);(root/'project-a').mkdir();(root/'project-b').mkdir()
        self.config={'namespace':{'owner_id':'test-owner','profile_id':'main'},'profile_home':str(root),'default_project':'a','projects':{'a':str(root/'project-a'),'b':str(root/'project-b')},'context_bytes':2000}
        self.store=Store(root/'state',self.config);self.store.initialize();self.store.bind('parent');self.store.bind('other',project='b');self.store.bind('child','parent',subagent=True)
    def tearDown(self):self.tmp.cleanup()
    def record(self,**kw):return self.store.record('parent',{'content':'Atlas хранит оригиналы документов в SQLite.','source_ref':'test:synthetic:1','kind':'note','request_id':'one','scope':'project',**kw})
    def test_revision_idempotency_and_readback(self):
        r=self.record();self.assertEqual(self.store.read('parent',r['id'])['content_hash'],r['content_hash']);self.assertTrue(self.record()['duplicate'])
        with self.assertRaises(ValueError):self.record(content='Changed')
        n=self.record(id=r['id'],request_id='two',expected_revision=1,content='Atlas хранит оригиналы в SQLite; индекс — производный.');self.assertEqual(n['revision'],2)
        with self.assertRaises(ValueError):self.record(id=r['id'],request_id='three',expected_revision=1)
    def test_cross_scope_isolation(self):
        r=self.record();self.assertEqual(self.store.local_search('other','Atlas')['records'],[])
        with self.assertRaises(PermissionError):self.store.read('other',r['id'])
    def test_children_read_only_and_inheritance(self):
        r=self.record(visibility={'allowed_roles':['parent','collector'],'evidence_use':'general'})
        self.store.assign('parent','child','collector','read assigned record','test-assignment')
        self.assertEqual(self.store.read('child',r['id'])['revision'],1)
        with self.assertRaises(PermissionError):self.store.record('child',{'content':'x'})
        with self.assertRaises(PermissionError):self.store.select_project('child','b')
        a=self.store.context('parent','Atlas','t');child=self.store.context('child','Atlas','c')
        self.assertNotEqual(child,a)
        self.assertEqual(json.loads(child.split('\n')[1])['records'][0]['id'],r['id'])
        with self.assertRaises(PermissionError):self.store.bind('orphan',subagent=True)
    def test_retraction(self):
        r=self.record();self.store.retract('parent',r['id'],1)
        self.assertEqual(self.store.local_search('parent','Atlas')['records'],[])
        with self.assertRaises(PermissionError):self.store.read('parent',r['id'],1)
    def test_secrets_and_paths(self):
        with self.assertRaises(ValueError):self.record(content='api_key=abcdefghijklmnopqrstuv')
        for path in ['../outside','/tmp/any','.env','secrets/auth.json']:
            with self.assertRaises(PermissionError):self.store.safe_file('parent',path)
        root=Path(self.config['projects']['a']);(root/'escape').symlink_to('/tmp')
        with self.assertRaises(PermissionError):self.store.safe_file('parent','escape/file')
    def test_whole_record_context_and_budget(self):
        r=self.record(content='Large '*1000);text=self.store.context('parent','Large','t');body=json.loads(text.split('\n')[1]);self.assertEqual(body['records'],[]);self.assertEqual(body['deferred_records'][0]['id'],r['id']);self.assertEqual(len(self.store.read('parent',r['id'])['content']),6000)
        with self.assertRaises(ValueError):self.record(content='x'*9000,request_id='too-large')
    def test_primary_failure_and_snapshot(self):
        self.record();dest=Path(self.tmp.name)/'copy.sqlite';self.store.snapshot(dest)
        recovered=Store(Path(self.tmp.name)/'recovered',self.config);recovered.root.mkdir();dest.rename(recovered.path)
        self.assertEqual(len(recovered.local_search('parent','Atlas')['records']),1)
        self.store.path.rename(self.store.path.with_suffix('.disabled'))
        with self.assertRaises(RuntimeError):self.store.local_search('parent','Atlas')
    def test_parent_scope_change_closes_child(self):
        self.store.select_project('parent','b')
        with self.assertRaises(PermissionError):self.store.context('child','Atlas','changed')
        with self.assertRaises(PermissionError):self.store.binding('child')
    def test_unknown_schema_fails_closed(self):
        with self.store.db() as c:c.execute('UPDATE meta SET value=\'3\' WHERE key=\'schema\'')
        with self.assertRaises(RuntimeError):self.store.local_search('parent','Atlas')

if __name__=='__main__':unittest.main()
