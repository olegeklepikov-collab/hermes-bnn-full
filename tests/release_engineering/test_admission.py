import importlib.util,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'packaging/admission.py'
if not P.exists():P=Path(__file__).with_name('admission.py')
spec=importlib.util.spec_from_file_location('release_admission',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Admission(unittest.TestCase):
 def setUp(self):self.release={'archive':{'sha256':'program-hash'},'source_commit':'source'}
 def receipt(self,gates,**extra):return {'archive_sha256':'program-hash','source_commit':'source','gates':gates,**extra}
 def test_empty_policy_denied(self):self.assertFalse(m.evaluate([],self.release,[])['eligible_for_production'])
 def test_missing_execution_denied(self):self.assertFalse(m.evaluate(['A'],self.release,[])['eligible_for_production'])
 def test_wrong_program_denied(self):self.assertFalse(m.evaluate(['A'],self.release,[self.receipt({'A':{'status':'passed','witness_sha256':'a'*64}},archive_sha256='other')])['eligible_for_production'])
 def test_status_without_witness_denied(self):self.assertFalse(m.evaluate(['A'],self.release,[self.receipt({'A':{'status':'passed'}})])['eligible_for_production'])
 def test_fixture_cannot_pass_live_model(self):self.assertFalse(m.evaluate(['live_model_and_subagents'],self.release,[self.receipt({'live_model_and_subagents':{'status':'passed','witness_sha256':'a'*64,'execution_kind':'fixture'}})])['eligible_for_production'])
 def test_conflict_denied(self):self.assertFalse(m.evaluate(['A'],self.release,[self.receipt({'A':{'status':'passed','witness_sha256':'a'*64}}),self.receipt({'A':{'status':'failed','witness_sha256':'b'*64}})])['eligible_for_production'])
 def test_machine_acceptance_completes_without_human(self):
  r=m.evaluate(['A','live_model_and_subagents'],self.release,[self.receipt({'A':{'status':'passed','witness_sha256':'a'*64},'live_model_and_subagents':{'status':'passed','witness_sha256':'b'*64,'execution_kind':'live_model'}})])
  self.assertTrue(r['eligible_for_production']);self.assertFalse(r['external_human_semantic_review_required']);self.assertFalse(r['production_deployment_authority_granted'])
if __name__=='__main__':unittest.main()
