import importlib.util,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
P=Path(__file__).resolve().parents[2]/'packaging/memory_readiness.py'
s=importlib.util.spec_from_file_location('readiness',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class ReadinessTests(unittest.TestCase):
    def test_missing_dataset_is_not_verified(self):
        d={'id':'one','scope':'project:p','status':'indexed','dataset':'old-instance-x'}
        result=m.cognee_binding('new-instance',[d],[])[0]
        self.assertFalse(result['instance_binding_matches']);self.assertFalse(result['native_dataset_present']);self.assertFalse(result['projection_verified'])
    def test_matching_dataset_still_needs_native_item_observation(self):
        scope='project:p';name='owner-'+m.hashlib.sha256(scope.encode()).hexdigest()[:24]
        d={'id':'one','scope':scope,'status':'indexed','dataset':name}
        result=m.cognee_binding('owner',[d],[name])[0]
        self.assertTrue(result['instance_binding_matches']);self.assertTrue(result['native_dataset_present']);self.assertFalse(result['projection_verified'])
    def test_tcp_success_is_not_health(self):
        sock=MagicMock();sock.__enter__.return_value.connect_ex.return_value=0
        with patch.object(m.socket,'socket',return_value=sock):result=m.listening('http://127.0.0.1:64000')
        self.assertEqual(result['status'],'listening_identity_unverified');self.assertFalse(result['service_health_verified'])
    def test_remote_endpoint_does_not_trigger_probe(self):
        with patch.object(m.socket,'socket') as connect:
            with self.assertRaises(ValueError):m.listening('https://example.org:443')
        connect.assert_not_called()
