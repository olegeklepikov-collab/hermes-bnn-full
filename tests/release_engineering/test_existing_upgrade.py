"""Recovery preserves unfriendly outcomes and every row, rather than chosen counts."""
import importlib.util,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from upgrade_existing import logical_database,backup_database,owned,rebind

class ExistingUpgrade(unittest.TestCase):
    def test_backup_restore_preserves_unknown_outcomes_and_binary_rows(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);source=r/'source.sqlite'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE ledger(id TEXT PRIMARY KEY,state TEXT,payload BLOB)')
                db.execute('INSERT INTO ledger VALUES(?,?,?)',('old','outcome_unknown',bytes(range(255))))
            original=logical_database(source)
            self.assertEqual(backup_database(source,r/'backup.sqlite'),original)
            self.assertEqual(backup_database(r/'backup.sqlite',r/'restored.sqlite'),original)
            with sqlite3.connect(r/'restored.sqlite') as db:db.execute("UPDATE ledger SET state='returned_usage_known'")
            self.assertNotEqual(logical_database(r/'restored.sqlite'),original)
            self.assertEqual(logical_database(source),original)

    def test_path_escape_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();(r/'link').symlink_to('/tmp')
            for p in [r.parent/'outside',r/'link/secret']:
                with self.assertRaises(PermissionError):owned(r,p)
            self.assertEqual(owned(r,r/'state/new'),r/'state/new')

    def test_program_rebind_retains_owner_keys_and_module_states(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();p=r/'Memory/releases/new';p.mkdir(parents=True);(p/'module.py').write_text('qualified')
            old={'namespace':{'owner_id':'owner','profile_id':'main'},'host_key':str(r/'key'),
                 'modules':{'gsd':{'state_root':str(r/'gsd-state'),'files':{str(r/'Memory/releases/old/module.py'):'old'}}}}
            out=rebind(old,r,p)
            self.assertEqual(out['namespace'],old['namespace']);self.assertEqual(out['host_key'],old['host_key'])
            self.assertEqual(out['modules']['gsd']['state_root'],old['modules']['gsd']['state_root'])
            self.assertEqual(out['path_relocations'][0]['owner_id'],'owner')
            self.assertNotIn('package_root',old)

if __name__=='__main__':unittest.main()
