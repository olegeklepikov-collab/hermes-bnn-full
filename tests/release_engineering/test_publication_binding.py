"""Regression for observed draft tag drift; never replace an existing draft by accident."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from publish_candidate import bound_release,release_body

class PublicationBinding(unittest.TestCase):
    def setUp(self):
        self.binding={'repository':'owner/repo','tag':'candidate','release_id':7}
        self.release={'id':7,'tag_name':'candidate'}
    def test_resume_is_bound_to_existing_release_id(self):
        self.assertEqual(bound_release([self.release],self.binding,'owner/repo','candidate'),self.release)
        self.assertIsNone(bound_release([],None,'owner/repo','candidate'))
    def test_observed_tag_drift_and_changed_binding_cannot_create_another_release(self):
        for releases,binding in [([{'id':7,'tag_name':'untagged-server-value'}],self.binding),
                                 ([],self.binding),([self.release],{**self.binding,'repository':'other/repo'})]:
            with self.subTest(releases=releases,binding=binding),self.assertRaises(PermissionError):
                bound_release(releases,binding,'owner/repo','candidate')
    def test_release_notes_use_actual_qualification_counts(self):
        body=release_body({'native_installations_passed':2,'release_engineering_unit_tests':49})
        self.assertIn('49',body);self.assertNotIn('40 проверок',body)

if __name__=='__main__':unittest.main()
