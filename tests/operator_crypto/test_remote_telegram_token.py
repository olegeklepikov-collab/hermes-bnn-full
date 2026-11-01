"""Actual Web Crypto -> Python JWE interoperability; synthetic keys and token only.

Requires Node.js and TEST's bundled cryptography; no network or real credentials.
Run: TEST_PYTHON -B -m unittest discover -s tests/operator_crypto -v
"""
import datetime
import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packaging'))
spec = importlib.util.spec_from_file_location('remote_transfer',ROOT/'packaging/remote_telegram_token.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RemoteTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.pem = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        now = datetime.datetime.now(datetime.timezone.utc)
        cls.binding = {'kid':'synthetic-key','instance_id':'TEST-synthetic','bot_username':'synthetic_test_bot',
            'issued_at':now.isoformat(),'expires_at':(now+datetime.timedelta(hours=24)).isoformat()}
        n = key.public_key().public_numbers()
        jwk = {'kty':'RSA','n':m.b64(n.n.to_bytes((n.n.bit_length()+7)//8,'big')),'e':'AQAB','alg':'RSA-OAEP-256','ext':True}
        html = (ROOT/'packaging/remote_telegram_token.html').read_text().replace('__PUBLIC_JWK__',json.dumps(jwk)).replace('__BINDING__',json.dumps(cls.binding))
        script = re.search(r'<script>([\s\S]+)</script>',html).group(1)
        cls.synthetic = '123456:'+'X'*32
        runner = '''const vm=require('node:vm'),crypto=require('node:crypto').webcrypto;
let text='';process.stdin.on('data',x=>text+=x);process.stdin.on('end',async()=>{
 const input=JSON.parse(text),elements={};
 const context=vm.createContext({crypto,TextEncoder,Uint8Array,btoa,Blob,URL,
  setTimeout:()=>0,document:{getElementById:id=>elements[id]??=( {value:'',textContent:'',hidden:true,disabled:false} ),createElement:()=>({click(){}})}});
 vm.runInContext(input.script,context);context.document.getElementById('secret').value=input.synthetic;
 await elements.encrypt.onclick();
 process.stdout.write(JSON.stringify({envelope:vm.runInContext('encryptedFile',context),field_cleared:elements.secret.value==='',download_enabled:!elements.download.hidden,status:elements.status.textContent}));
});'''
        result = subprocess.run(['node','-e',runner],input=json.dumps({'script':script,'synthetic':cls.synthetic}),
            text=True,capture_output=True,timeout=20,check=True)
        cls.ui = json.loads(result.stdout)
        cls.envelope = cls.ui['envelope']

    def test_actual_javascript_encryption_python_decryption_and_field_clearing(self):
        self.assertEqual(m.decrypt(self.envelope,self.binding,self.pem),self.synthetic)
        self.assertTrue(self.ui['field_cleared'])
        self.assertTrue(self.ui['download_enabled'])
        self.assertNotIn(self.synthetic,self.envelope)

    def test_modified_authentication_tag_refused(self):
        parts = self.envelope.split('.')
        tag = bytearray(m.unb64(parts[-1]));tag[0] ^= 1;parts[-1] = m.b64(tag)
        with self.assertRaisesRegex(ValueError,'encrypted_transfer_invalid'):
            m.decrypt('.'.join(parts),self.binding,self.pem)

    def test_another_instance_refused_even_with_the_same_key(self):
        with self.assertRaises(ValueError):
            m.decrypt(self.envelope,{**self.binding,'instance_id':'another-TEST'},self.pem)

    def test_expired_transfer_refused(self):
        future = datetime.datetime.fromisoformat(self.binding['expires_at'])+datetime.timedelta(seconds=1)
        with self.assertRaises(ValueError):
            m.decrypt(self.envelope,self.binding,self.pem,now=future)


if __name__=='__main__':
    unittest.main()
