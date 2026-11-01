"""New owned directories in a verified neutral cache do not become opaque dependencies."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
from release_cli import dependency_inventory


class SourceDirectoryClassification(unittest.TestCase):
    def test_new_owned_directories_allow_only_declared_files(self):
        directory={'type':'directory','mode':0o755}
        binary={'type':'file','mode':0o755,'bytes':4,'sha256':'0'*64}
        source={'Memory/new/module.py'}
        actual={'Memory/new':directory,'Memory/new/module.py':binary,'runtime/python':binary}
        expected={'runtime/python':binary}
        self.assertEqual(dependency_inventory(actual,expected,source,{'Memory/new':directory}),expected)
        actual['Memory/new/unclassified.bin']=binary
        self.assertNotEqual(dependency_inventory(actual,expected,source,{'Memory/new':directory}),expected)

    def test_directory_permissions_and_locked_directory_still_checked(self):
        directory={'type':'directory','mode':0o755}
        with self.assertRaises(PermissionError):
            dependency_inventory({'owned':{'type':'directory','mode':0o777}},{},set(),{'owned':directory})
        expected={'locked':directory}
        altered={'locked':{'type':'directory','mode':0o700}}
        self.assertNotEqual(dependency_inventory(altered,expected,set(),{'locked':directory}),expected)


if __name__=='__main__':unittest.main()
