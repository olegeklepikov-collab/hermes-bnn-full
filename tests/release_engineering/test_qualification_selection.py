"""Qualifying another candidate must not abandon the selected profile's task graph/auth."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from qualify_native import register_qualification

class QualificationSelection(unittest.TestCase):
    def test_first_qualification_can_initialize_the_empty_role(self):
        result=register_qualification({},'test',{'instance_id':'new'})
        self.assertEqual(result['test']['instance_id'],'new')
    def test_requalification_preserves_existing_roles_and_does_not_mutate_input(self):
        original={'development':{'instance_id':'persistent-tasks'},'test':{'instance_id':'existing-auth'}}
        result=register_qualification(original,'test',{'instance_id':'fresh-candidate'})
        self.assertEqual(result['test']['instance_id'],'existing-auth')
        self.assertEqual(result['development']['instance_id'],'persistent-tasks')
        self.assertEqual(result['_qualified_candidates']['test']['instance_id'],'fresh-candidate')
        self.assertNotIn('_qualified_candidates',original)

if __name__=='__main__':unittest.main()
