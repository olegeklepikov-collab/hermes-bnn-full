import unittest,sys,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from storage_capacity import admission,GIB
from program_archive_retention import plan

class StorageCapacity(unittest.TestCase):
 def test_working_headroom_is_preserved_after_full_archive(self):
  with self.assertRaises(OSError):admission(10*GIB,6*GIB)
  self.assertEqual(admission(14*GIB,6*GIB)['protected'],6*GIB)
 def test_only_two_latest_program_archives_are_retained_by_semantic_version(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for n in [8,11,12]:
    d=root/str(n);d.mkdir();name='Hermes-'+str(n)+'.tar.gz';(d/name).write_bytes(b'x')
    (d/'RELEASE.json').write_text(json.dumps({'version':'2026.11.'+str(n),'build_id':str(n),'archive':{'name':name,'sha256':'test'},'owner_data_included':False,'credentials_included':False}))
   v=plan(root);self.assertEqual(len(v['preserved']),2);self.assertEqual(v['eligible'][0]['build_id'],'8')
   d=root/'8';m=json.loads((d/'RELEASE.json').read_text());m['owner_data_included']=True;(d/'RELEASE.json').write_text(json.dumps(m));self.assertEqual(plan(root)['eligible'],[])
