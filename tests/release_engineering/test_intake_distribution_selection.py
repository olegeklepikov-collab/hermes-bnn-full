"""Fresh install must use the exact qualified wheel, not a historical filename."""
from pathlib import Path
import importlib.util,json,tempfile,unittest
p=Path(__file__).resolve().parents[2]/'product/bootstrap_full.py'
s=importlib.util.spec_from_file_location('fresh_bootstrap',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


class DistributionSelection(unittest.TestCase):
    def fixture(self,root,version='0.14.8',name=None,declared=None):
        (root/'Intake/packages').mkdir(parents=True,exist_ok=True);(root/'configuration').mkdir(exist_ok=True)
        (root/'Intake/packages/manifest.json').write_text(json.dumps({'contract':'BNNIntakeDistributionV1','version':version,'wheel':name or 'hermes_bnn_intake-'+version+'-py3-none-any.whl'}))
        (root/'configuration/full-source.json').write_text(json.dumps({'Intake':declared or version}))
    def test_current_and_future_numeric_versions_select_their_own_library(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d)
            for version in ['0.14.8','1.0.0']:
                self.fixture(r,version);meta,wheel,library=m.intake_distribution(r)
                self.assertEqual(library,r/'Hermes/Intake'/version);self.assertIn(version,wheel.name)
    def test_historical_filename_or_mismatching_product_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d)
            for extra in [{'name':'hermes_bnn_intake-0.14.7-py3-none-any.whl'},{'declared':'0.14.7'}]:
                self.fixture(r,**extra)
                with self.assertRaises(PermissionError):m.intake_distribution(r)
    def test_filename_escape_is_rejected_before_any_unpack(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);self.fixture(r,name='../../untrusted.whl')
            with self.assertRaises(PermissionError):m.intake_distribution(r)
