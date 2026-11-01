"""The observed native install failure must be detected before packing gigabytes."""
import hashlib
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from pair_contract import verify_pair,verify_pins,verify_runtime_origin

class PairContract(unittest.TestCase):
    def test_actual_source_wheel_and_native_pair(self):
        value=verify_pair(Path(__file__).resolve().parents[2])
        self.assertEqual(value['Memory'],'2.0.0-dev.46');self.assertEqual(value['Intake'],'0.14.5')
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
