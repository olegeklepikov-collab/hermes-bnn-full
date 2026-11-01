"""Regression for the observed hardcoded dev.45 exception corrupting dev.46 pins."""
import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'product'))
from neutral_relocate import run
from bootstrap_preflight import compute_pin

class VersionedRelocation(unittest.TestCase):
    def test_any_memory_version_stays_immutable_and_preflight_uses_template(self):
        with tempfile.TemporaryDirectory() as d:
            bundle=Path(d);root=bundle/'Hermes';package=root/'Memory/releases/2.0.0-dev.99'
            package.mkdir(parents=True);(bundle/'configuration').mkdir()
            pin={'runtime_root':'__HERMES_ROOT__/runtime/test','os_release':'synthetic'}
            raw=json.dumps(pin).encode();(package/'compute-runtime.json').write_bytes(raw)
            identity=root/'Identity/releases/0.2.1';identity.mkdir(parents=True)
            (identity/'manifest.json').write_text('{}')
            ordinary=root/'settings.txt';ordinary.write_text('__HERMES_ROOT__/workspace')
            (bundle/'configuration/copy-plan.json').write_text(json.dumps({'files':['settings.txt'],'trees':['Memory/releases/2.0.0-dev.99'],'source_root':'__HERMES_ROOT__'}))
            (bundle/'configuration/memory.template.json').write_text(json.dumps({'package_root':'__HERMES_ROOT__/Memory/releases/2.0.0-dev.99'}))
            run(bundle,Path('/synthetic-old-root'))
            self.assertEqual((package/'compute-runtime.json').read_bytes(),raw)
            self.assertEqual(ordinary.read_text(),str(root/'workspace'))
            self.assertEqual(compute_pin(bundle),pin)
    def test_preflight_cannot_read_an_external_package(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'configuration').mkdir()
            (p/'configuration/memory.template.json').write_text(json.dumps({'package_root':'/outside/Memory/releases/v1'}))
            with self.assertRaises(PermissionError):compute_pin(p)

if __name__=='__main__':unittest.main()
