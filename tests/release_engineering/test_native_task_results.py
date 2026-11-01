"""Saved worker results: real SQLite scoping, pagination and revision checks; no LLM claim."""
import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'product/Hermes/Memory/releases'/json.loads((ROOT/'locks/product.lock.json').read_text())['components']['Memory']
sys.path.insert(0,str(PACKAGE))
from bn_memory.teams import Team
from bn_memory.store import canonical,sha


class Store:
    profile='profile-a'
    def __init__(self):
        self.connection=sqlite3.connect(':memory:')
        self.connection.row_factory=sqlite3.Row
    @contextlib.contextmanager
    def db(self):
        yield self.connection
        self.connection.commit()
    def writable(self,sid):
        if sid!='parent-a':raise PermissionError('foreign parent')


class SavedResults(unittest.TestCase):
    def setUp(self):
        self.store=Store();host=SimpleNamespace(store=self.store)
        def load(sid,run):
            return {'sid':{'work-a':'parent-a','work-b':'parent-b'}[run]},{}
        self.team=Team(SimpleNamespace(host=host,module='base',load=load))
        self.product={'task_id':'task-a','role':'computation','status':'unreviewed',
                      'findings':['13+29=42'],'sources':[],'needs':[],'limitations':[]}
        self.save()
    def tearDown(self):self.store.connection.close()
    def save(self,state='succeeded',revision=4,profile='profile-a',run='work-a'):
        body={'role':'computation','product':self.product,'output_sha256':'a'*64,
              'receipt':{'handle':{'capability':'synthetic-private-capability'}}}
        self.store.connection.execute('INSERT OR REPLACE INTO native_tasks VALUES(?,?,?,?,?,?,?,?)',
                (profile,'task-a','parent-a',run,'bead-a',revision,state,canonical(body)))
    def read(self,**change):
        return self.team.result('parent-a','work-a',{'task_id':'task-a','expected_revision':4,**change})
    def test_small_result_and_no_private_handle(self):
        before=self.store.connection.total_changes;result=self.read()
        self.assertEqual(json.loads(result['text']),self.product)
        self.assertEqual(result['product_sha256'],sha(canonical(self.product)))
        self.assertEqual(result['native_output_sha256'],'a'*64)
        self.assertEqual(result['evidence_status'],'unreviewed')
        self.assertTrue(result['complete']);self.assertFalse(result['has_more'])
        self.assertNotIn('synthetic-private-capability',canonical(result))
        self.assertEqual(self.store.connection.total_changes,before)
    def test_full_large_unicode_product_has_no_truncation(self):
        self.product['findings']=['Данные\r\n日本語 😀 '*2000];self.save()
        pieces=[];offset=0
        while True:
            page=self.read(offset=offset,page_size=73);pieces.append(page['text'])
            self.assertEqual(page['fragment_sha256'],sha(page['text']))
            self.assertEqual(page['product_sha256'],sha(canonical(self.product)))
            self.assertFalse(page['complete'])
            if not page['has_more']:break
            self.assertEqual(page['next_offset'],offset+len(page['text']));offset=page['next_offset']
        self.assertEqual(''.join(pieces),canonical(self.product))
        self.assertTrue(page['page_reaches_end'])
    def test_other_parent_work_and_unknown_task_are_denied(self):
        with self.assertRaises(PermissionError):self.team.result('parent-b','work-a',{'task_id':'task-a','expected_revision':4})
        with self.assertRaises(PermissionError):self.team.result('parent-a','work-b',{'task_id':'task-a','expected_revision':4})
        with self.assertRaises(PermissionError):self.read(task_id='other-task')
        self.product['findings']=['another profile'];self.save(profile='profile-b')
        self.assertEqual(json.loads(self.read()['text'])['findings'],['13+29=42'])
    def test_revision_change_between_pages_is_denied(self):
        self.read(page_size=10);self.save(revision=5)
        with self.assertRaisesRegex(PermissionError,'revision_changed'):self.read(offset=10,page_size=10)
    def test_unfinished_results_denied_needs_remains_readable(self):
        for state in ['running','unknown','blocked','cancelled','launch_reserved']:
            self.save(state=state)
            with self.subTest(state=state),self.assertRaises(PermissionError):self.read()
        self.product['needs']=['Missing original'];self.save(state='needs')
        self.assertEqual(json.loads(self.read()['text'])['needs'],['Missing original'])
    def test_invalid_integer_bounds_include_bool_and_none(self):
        for args in [{'expected_revision':None},{'expected_revision':True},{'expected_revision':0},
                     {'offset':-1},{'offset':True},{'page_size':0},{'page_size':8193},
                     {'page_size':False},{'page_size':None},{'task_id':''}]:
            with self.subTest(args=args),self.assertRaises(ValueError):self.read(**args)
    def test_end_offset_does_not_claim_complete_reading(self):
        length=len(canonical(self.product));page=self.read(offset=length)
        self.assertEqual(page['text'],'');self.assertFalse(page['complete'])
        self.assertTrue(page['page_reaches_end']);self.assertIsNone(page['next_offset'])
        with self.assertRaises(ValueError):self.read(offset=length+1)
    def test_corrupt_product_binding_is_denied(self):
        self.product['task_id']='foreign-task';self.save()
        with self.assertRaisesRegex(PermissionError,'binding_invalid'):self.read()
    def test_base_and_completed_research_routes_use_the_same_reader(self):
        from bn_memory.base_work import BaseWork
        from bn_memory.research_module import Research
        host=self.team.host
        host.admission=SimpleNamespace(ready=lambda *a:None)
        host.modules=SimpleNamespace(require=lambda *a:None)
        host.working=SimpleNamespace(binding=lambda sid:'work-a')
        args={'action':'result','task_id':'task-a','expected_revision':4}
        base=BaseWork(host);base.load=self.team.research.load
        self.assertEqual(json.loads(base.call('parent-a','turn',args)['text']),self.product)
        research=Research.__new__(Research);research.host=host
        research.load=lambda sid,run:({'sid':'parent-a','state':'complete'}, {})
        actual=research.call('parent-a','turn','udr_team',{**args,'run_id':'work-a'})
        self.assertEqual(json.loads(actual['text']),self.product)


if __name__=='__main__':unittest.main()
