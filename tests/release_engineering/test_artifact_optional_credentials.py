"""File delivery must work before optional external providers are configured."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERSION = json.loads((ROOT/'locks/product.lock.json').read_text())['components']['Memory']
PACKAGE = ROOT/'product/Hermes/Memory/releases'/VERSION
sys.path.insert(0,str(PACKAGE))
spec = importlib.util.spec_from_file_location('qualified_artifacts',PACKAGE/'bn_memory/artifacts.py')
module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class OptionalCredentials(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host_key = self.root/'host.key';self.host_key.write_bytes(b'synthetic-host-authority-key')
        self.voyage = self.root/'voyage.key'
        self.artifacts = module.Artifacts.__new__(module.Artifacts)
        self.artifacts.root = self.root/'artifacts'
        self.artifacts.cfg = {'host_key':str(self.host_key),'voyage_key_file':str(self.voyage),
                              'profile_home':str(self.root/'profile')}

    def tearDown(self):
        self.temp.cleanup()

    def test_absent_optional_key_is_allowed_and_present_key_is_still_protected(self):
        values = self.artifacts.secrets()
        self.assertIn(self.host_key.read_bytes(),values)
        self.artifacts.sensitive('Обычный синтетический файл'.encode(),values)
        secret = b'synthetic-voyage-credential-for-test'
        self.voyage.write_bytes(secret)
        with self.assertRaises(PermissionError):
            self.artifacts.sensitive(b'leak: '+secret,self.artifacts.secrets())

    def test_missing_required_host_key_still_blocks(self):
        self.artifacts.cfg['host_key']=str(self.root/'missing-required.key')
        with self.assertRaises(FileNotFoundError):
            self.artifacts.secrets()


if __name__=='__main__':
    unittest.main()
