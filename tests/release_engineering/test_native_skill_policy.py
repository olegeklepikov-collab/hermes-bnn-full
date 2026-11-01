import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from native_skill_policy import compile_bundled

class NativeSkills(unittest.TestCase):
    def test_supplied_native_reference_is_explicit_and_parent_only(self):
        root=Path(__file__).resolve().parents[2]/'product/Hermes/hermes-agent'
        rule,files=compile_bundled(root)
        self.assertIn('hermes-agent',rule['arguments_schema']['properties']['name']['enum'])
        self.assertEqual(rule['roles'],['parent']);self.assertGreater(len(files),50)
        self.assertFalse(rule['arguments_schema']['additionalProperties'])
        self.assertNotIn('*',rule['arguments_schema']['properties']['name']['enum'])
    def test_linked_document_outside_supplied_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'skills/x').mkdir(parents=True);(root/'outside').write_text('name: unsafe')
            (root/'skills/x/SKILL.md').symlink_to(root/'outside')
            with self.assertRaises(PermissionError):compile_bundled(root)
    def test_ambiguous_name_does_not_expand_permission(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for n in ['a','b']:
                p=root/'skills'/n;p.mkdir(parents=True);(p/'SKILL.md').write_text('---\nname: same\n---\n')
            with self.assertRaises(PermissionError):compile_bundled(root)

if __name__=='__main__':unittest.main()
