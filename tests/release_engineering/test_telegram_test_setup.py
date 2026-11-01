"""Credential intake must refuse wrong ownership before writing TEST or calling Telegram."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'packaging'))
spec = importlib.util.spec_from_file_location('test_telegram_setup', ROOT/'packaging/telegram_test_setup.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class TelegramSetupTests(unittest.TestCase):
    def test_only_witnessed_telegram_delta_can_be_enrolled(self):
        import copy
        home = Path('/isolated/test/Hermes')
        before = {'delivery':{'bot_username':''},'controls':{'required':True}}
        after = copy.deepcopy(before)
        after['delivery'].update(bot_username='separate_test_bot',recipient_user_id='123',
            profile_home=str(home/'data'),telegram_key_file=str(home/'private/telegram.token'),
            recipient_file=str(home/'private/telegram-recipient.json'))
        m.delivery_change(before,after,home,{'username':'separate_test_bot'},'123')
        after['controls']['required']=False
        with self.assertRaisesRegex(PermissionError,'unrelated_settings_change'):
            m.delivery_change(before,after,home,{'username':'separate_test_bot'},'123')

    def test_occupied_bot_and_malformed_token_refused(self):
        token = '123456:'+'X'*32
        with self.assertRaises(PermissionError):
            m.validate_input('@ExistingBot', token, ['existingbot'])
        for invalid in ['short', '123:with\nnewline', '123:'+('X'*30)+'?leak=yes']:
            with self.assertRaises(ValueError):
                m.validate_input('separate_test_bot', invalid)

    def test_production_outside_test_root_refused_before_filesystem_read(self):
        with patch.object(m.release,'read',return_value={'test':{'installation':'/production/Hermes'}}), \
             patch.object(m.release,'resources',return_value={'test_root':'/isolated-test'}):
            with self.assertRaisesRegex(PermissionError,'qualified_TEST_root_required'):
                m.selected_test()

    def test_exception_does_not_expose_token_or_remote_url(self):
        secret = '123456:'+'X'*32
        with patch.object(m.urllib.request,'build_opener',side_effect=RuntimeError('before request')):
            # Transport construction does not involve a secret URL in its exception.
            with self.assertRaisesRegex(RuntimeError,'before request'):
                m.bot_call(secret,'getMe')
        class Broken:
            def open(self,*args,**kwargs):
                raise RuntimeError('https://api.telegram.org/bot'+secret+'/getMe')
        with patch.object(m.urllib.request,'build_opener',return_value=Broken()):
            with self.assertRaises(ConnectionError) as caught:
                m.bot_call(secret,'getMe')
            self.assertNotIn(secret,str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)


if __name__ == '__main__':
    unittest.main()
