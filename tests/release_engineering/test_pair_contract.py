"""The observed native install failure must be detected before packing gigabytes."""
import hashlib,json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from pair_contract import verify_pair,verify_pins,verify_runtime_origin,verify_version

class PairContract(unittest.TestCase):
    def test_runtime_label_must_match_directory_and_release(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'2.0.0-dev.47';(p/'bn_memory').mkdir(parents=True)
            (p/'bn_memory/__init__.py').write_text("__version__ = '2.0.0-dev.46'\n")
            (p/'release.json').write_text(json.dumps({'version':'2.0.0-dev.47'}))
            with self.assertRaisesRegex(PermissionError,'memory_runtime_version_mismatch'):
                verify_version(p,'2.0.0-dev.47')
            (p/'bn_memory/__init__.py').write_text("__version__ = '2.0.0-dev.47'\n")
            verify_version(p,'2.0.0-dev.47')
    def test_actual_source_wheel_and_native_pair(self):
        root=Path(__file__).resolve().parents[2];value=verify_pair(root)
        lock=json.loads((root/'locks/product.lock.json').read_text())['components']
        self.assertEqual(value['Memory'],lock['Memory']);self.assertEqual(value['Intake'],lock['Intake'])
    def test_changed_memory_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'manifest.json').write_bytes(b'new-manifest')
            with self.assertRaisesRegex(PermissionError,'unqualified_component_pair'):
                verify_pins(p,p,{'memory_files':{'manifest.json':hashlib.sha256(b'old-manifest').hexdigest()},'core_files':{}})
    def test_changed_core_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'control.py').write_bytes(b'changed-control')
            with self.assertRaisesRegex(PermissionError,'unqualified_component_pair'):
                verify_pins(p,p,{'memory_files':{},'core_files':{'control.py':'0'*64}})
    def test_relative_runtime_marker_cannot_reach_full_packaging(self):
        with self.assertRaises(PermissionError):
            verify_runtime_origin({'runtime_root':'__HERMES_ROOT__/runtime/python/version','python':'__HERMES_ROOT__/runtime/python/version/bin/python'},
                                  {'python':'__HERMES_ROOT__/DocumentRuntime/python','python_roots':['__HERMES_ROOT__/DocumentRuntime']})

if __name__=='__main__':unittest.main()
