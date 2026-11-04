import importlib.util,unittest,sqlite3,json,hashlib
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'packaging/embedding_queue_plan.py';s=importlib.util.spec_from_file_location('queue_plan',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class QueuePlanTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.h='a'*64
        self.c.executescript('CREATE TABLE semantic_chunks(id TEXT,scope TEXT,state TEXT,hash TEXT);CREATE TABLE embedding_cache_v2(contract_hash TEXT,text_sha256 TEXT);CREATE TABLE embedding_attempts(contract_hash TEXT,status TEXT,input_hashes TEXT);')
    def tearDown(self):self.c.close()
    def row(self,i,scope='project:a'):
        h=hashlib.sha256(str(i).encode()).hexdigest();self.c.execute('INSERT INTO semantic_chunks VALUES(?,?,?,?)',(str(i),scope,'pending',h));return h
    def unknown(self,hs):self.c.execute('INSERT INTO embedding_attempts VALUES(?,?,?)',(self.h,'outcome_or_usage_unknown',json.dumps(hs)))
    def test_unknown_front_does_not_starve_independent_tail(self):
        self.unknown([self.row(i) for i in range(32)]);self.row(32)
        result=m.eligible(self.c,self.h,['project:a']);self.assertEqual([r['id'] for r in result],['32'])
        self.assertEqual(self.c.execute('SELECT status FROM embedding_attempts').fetchone()[0],'outcome_or_usage_unknown')
    def test_cached_same_contract_only(self):
        h=self.row(1);self.unknown([h]);self.c.execute('INSERT INTO embedding_cache_v2 VALUES(?,?)',('b'*64,h));self.assertEqual(m.eligible(self.c,self.h,['project:a']),[])
        self.c.execute('INSERT INTO embedding_cache_v2 VALUES(?,?)',(self.h,h));self.assertEqual(len(m.eligible(self.c,self.h,['project:a'])),1)
    def test_scope_and_limit_are_applied_before_selection(self):
        self.row(0,scope='project:other');self.row(1);self.row(2)
        self.assertEqual([r['id'] for r in m.eligible(self.c,self.h,['project:a'],1)],['1'])
        with self.assertRaises(ValueError):m.eligible(self.c,self.h,[],1)
        with self.assertRaises(ValueError):m.eligible(self.c,self.h,['project:a'],0)
