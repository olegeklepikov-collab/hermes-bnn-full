"""Recovery preserves unfriendly outcomes and every row, rather than chosen counts."""
import importlib.util,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from upgrade_existing import logical_database,backup_database,owned,rebind,apply_core_replacements

class ExistingUpgrade(unittest.TestCase):
    def test_all_core_replacements_including_new_adapter_use_artifact_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();root=r/'runtime';artifact=r/'artifact';root.mkdir();artifact.mkdir()
            (root/'hermes-agent/agent').mkdir(parents=True);(root/'hermes-agent/agent/existing.py').write_text('old')
            replacements={};pins={}
            for name in ['existing.py','new_adapter.py']:
                p=artifact/name;p.write_text('qualified '+name);h=hashlib.sha256(p.read_bytes()).hexdigest()
                replacements['hermes-agent/agent/'+name]={'source':str(p),'sha256':h};pins['agent/'+name]=h
            apply_core_replacements(root,replacements,pins)
            self.assertEqual((root/'hermes-agent/agent/new_adapter.py').read_text(),'qualified new_adapter.py')
            self.assertEqual((root/'hermes-agent/agent/existing.py').read_text(),'qualified existing.py')

    def test_bad_later_core_source_cannot_partially_replace_earlier_file(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();root=r/'runtime';root.mkdir();(root/'hermes-agent').mkdir();target=root/'hermes-agent/first.py';target.write_text('old')
            source=r/'candidate';source.write_text('candidate');import hashlib;h=hashlib.sha256(source.read_bytes()).hexdigest()
            values={'hermes-agent/first.py':{'source':str(source),'sha256':h},'hermes-agent/second.py':{'source':str(source),'sha256':'0'*64}}
            with self.assertRaises(PermissionError):apply_core_replacements(root,values,{'first.py':h,'second.py':'0'*64})
            self.assertEqual(target.read_text(),'old');self.assertFalse((root/'hermes-agent/second.py').exists())
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

    def test_known_placeholder_is_replaced_only_for_its_exact_owner_root(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();base={'namespace':{'owner_id':'owner','profile_id':'main'},'modules':{},
                'path_relocations':[{'from':'__HERMES_ROOT__','to':str(r),'owner_id':'owner'}]}
            out=rebind(base,r,r/'Memory/releases/new')
            self.assertEqual([x['from'] for x in out['path_relocations']],['/opt/hermes-bnn-distribution'])
            base['path_relocations'][0]['owner_id']='another-owner'
            with self.assertRaisesRegex(PermissionError,'exact_own_root'):
                rebind(base,r,r/'Memory/releases/new')

if __name__=='__main__':unittest.main()


class ControlWaitPolicyTests(unittest.TestCase):
    def test_only_historical_default_changes_required_controls_preserved(self):
        from upgrade_existing import control_wait_policy
        current={'version':1,'required':{'tool':['mandatory']},'timeout_seconds':5}
        result=control_wait_policy(current,30)
        self.assertEqual(result['required'],current['required'])
        self.assertEqual(result['timeout_seconds'],30)
        self.assertEqual(current['timeout_seconds'],5)
        self.assertEqual(control_wait_policy({**current,'timeout_seconds':12},30)['timeout_seconds'],12)
        with self.assertRaises(PermissionError):control_wait_policy(current,0)
        with self.assertRaises(PermissionError):control_wait_policy(current,61)


class CurrentInstalledPairTests(unittest.TestCase):
    def test_locked_release_pair_remains_a_supported_future_upgrade_source(self):
        from upgrade_existing import SUPPORTED_PAIRS
        root = Path(__file__).resolve().parents[2]
        components = json.loads((root / 'locks/product.lock.json').read_text())['components']
        self.assertIn(components['Intake'], SUPPORTED_PAIRS.get(components['Memory'], set()))

    def qualified_root(self, directory):
        import shutil
        source = Path(__file__).resolve().parents[2] / 'product/Hermes'
        root = Path(directory).resolve() / 'runtime'
        package = root / 'Memory/releases/2.0.0-dev.53'
        shutil.copytree(source / 'Memory/releases/2.0.0-dev.53', package)
        pins = json.loads((package / 'release.json').read_text())['core_patch_sha256']
        for name in pins:
            target = root / 'hermes-agent' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / 'hermes-agent' / name, target)
        return root, package

    def test_exact_current_memory_program_is_a_supported_upgrade_source(self):
        from upgrade_existing import verify_old
        with tempfile.TemporaryDirectory() as directory:
            root, package = self.qualified_root(directory)
            self.assertEqual(verify_old(root, {'package_root': str(package)}), package)

    def test_current_version_does_not_admit_changed_memory_bytes(self):
        from upgrade_existing import verify_old
        with tempfile.TemporaryDirectory() as directory:
            root, package = self.qualified_root(directory)
            with (package / 'bn_memory/checkpoint.py').open('a') as handle:
                handle.write('\n# Different program bytes\n')
            with self.assertRaisesRegex(PermissionError, 'old_memory_program_changed'):
                verify_old(root, {'package_root': str(package)})

    def test_current_version_does_not_admit_changed_core_bytes(self):
        from upgrade_existing import verify_old
        with tempfile.TemporaryDirectory() as directory:
            root, package = self.qualified_root(directory)
            target = root / 'hermes-agent/agent/compression_checkpoint.py'
            target.write_text(target.read_text() + '\n# Different core bytes\n')
            with self.assertRaisesRegex(PermissionError, 'old_core_program_changed'):
                verify_old(root, {'package_root': str(package)})
