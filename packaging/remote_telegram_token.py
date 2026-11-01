"""One-use encrypted token transfer to the existing qualified TEST intake.

Run with TEST's bundled Python (cryptography). Private keys remain outside Git.
Only ciphertext can be accepted from an attachment; plaintext is never printed.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import urllib.parse
import urllib.request
from pathlib import Path

import release_cli as release
from telegram_test_setup import selected_test, validate_input


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def unb64(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise ValueError('invalid_JWE_encoding')
    return base64.urlsafe_b64decode(value+'='*((-len(value))%4))


def decrypt(envelope, binding, key_bytes, now=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not 1 <= len(envelope) <= 8192:
        raise ValueError('invalid_JWE_size')
    try:
        header, wrapped, iv, ciphertext, tag = envelope.strip().split('.')
        expected = {'alg':'RSA-OAEP-256','enc':'A256GCM','kid':binding['kid']}
        if json.loads(unb64(header)) != expected:
            raise ValueError()
        key = serialization.load_pem_private_key(key_bytes,password=None)
        cek = key.decrypt(unb64(wrapped),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        nonce, seal = unb64(iv), unb64(tag)
        if len(cek)!=32 or len(nonce)!=12 or len(seal)!=16:
            raise ValueError()
        payload = json.loads(AESGCM(cek).decrypt(nonce,unb64(ciphertext)+seal,header.encode('ascii')))
        if set(payload) != {'binding','token','created_at'} or payload['binding'] != binding:
            raise ValueError()
        created = datetime.datetime.fromisoformat(payload['created_at'].replace('Z','+00:00'))
        issued = datetime.datetime.fromisoformat(binding['issued_at'])
        expires = datetime.datetime.fromisoformat(binding['expires_at'])
        if not issued-datetime.timedelta(minutes=5) <= created <= now+datetime.timedelta(minutes=5) or now>expires:
            raise ValueError()
        validate_input(binding['bot_username'],payload['token'])
        return payload['token']
    except Exception:
        # Crypto and transport errors must never reveal input values or token URLs.
        raise ValueError('encrypted_transfer_invalid_expired_or_for_another_instance') from None


def prepare():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    selected, home, _ = selected_test()
    case = home.parent.parent/'telegram-connection'
    form = release.read(case/'form.json')
    if (case/'connection.json').exists() or (case/'apply-started.json').exists():
        raise PermissionError('inspect_existing_connection_effects_first')
    if form['profile_home'] != str(home/'data'):
        raise PermissionError('TEST_form_binding_changed')
    if not re.fullmatch(r'[1-9]\d*',form.get('owner_user_id','')):
        raise PermissionError('confirmed_owner_binding_required')
    op = release.ROOT.parent/'.operator'
    active = op/'remote-telegram-current.json'
    if active.exists():
        saved = release.read(active)
        if saved['binding']['instance_id'] != selected['instance_id']:
            raise PermissionError('existing_transfer_for_another_instance')
        print(json.dumps({'html':saved['html'],'expires_at':saved['binding']['expires_at'],'existing_request':True}));return
    os.umask(0o077)
    request_id = secrets.token_hex(16)
    private = op/'telegram-transfer'/request_id
    private.mkdir(parents=True,mode=0o700)
    key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
    der = key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Owner is a confirmed runtime binding, never inferred from an incoming attachment.
    binding = {'transfer_id':request_id,'kid':b64(hashlib.sha256(der).digest()),
        'purpose':'Hermes BNN TEST Telegram connection','instance_id':selected['instance_id'],
        'profile_home':str(home/'data'),'bot_username':form['bot_username'],
        'owner_user_id':form['owner_user_id'],'issued_at':now.isoformat(),'expires_at':(now+datetime.timedelta(hours=24)).isoformat()}
    pem = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    with (private/'recipient.pem').open('xb') as stream:
        stream.write(pem)
    (private/'recipient.pem').chmod(0o600)
    n = key.public_key().public_numbers()
    jwk = {'kty':'RSA','n':b64(n.n.to_bytes((n.n.bit_length()+7)//8,'big')),
           'e':b64(n.e.to_bytes((n.e.bit_length()+7)//8,'big')),'alg':'RSA-OAEP-256','ext':True}
    public = case/'remote-input'
    public.mkdir(mode=0o700)
    template = (release.ROOT/'packaging/remote_telegram_token.html').read_text()
    rendered = template.replace('__PUBLIC_JWK__',json.dumps(jwk)).replace('__BINDING__',json.dumps(binding,ensure_ascii=False))
    out = public/'Hermes-BNN-TEST-Telegram.html'
    out.write_text(rendered)
    release.write(private/'request.json',{'binding':binding,'key_file':str(private/'recipient.pem'),
        'html':str(out),'form_url':form['url'],'html_sha256':release.digest(out),'consumed':False})
    release.write(active,release.read(private/'request.json'))
    print(json.dumps({'html':str(out),'expires_at':binding['expires_at'],'recipient_fingerprint':binding['kid'],'credentials_included':False}))


def prepare_mobile():
    selected, home, _ = selected_test()
    active = release.ROOT.parent/'.operator/remote-telegram-current.json'
    request = release.read(active)
    if request['consumed'] or request['binding']['instance_id'] != selected['instance_id']:
        raise PermissionError('current_unused_TEST_transfer_required')
    if datetime.datetime.now(datetime.timezone.utc)>datetime.datetime.fromisoformat(request['binding']['expires_at']):
        raise PermissionError('transfer_expired')
    binding = {k:v for k,v in request['binding'].items() if k not in {'profile_home','owner_user_id'}}
    binding['target_binding_sha256'] = hashlib.sha256(json.dumps(request['binding'],sort_keys=True).encode()).hexdigest()
    original = Path(request['html']).read_text()
    jwk = json.loads(re.search(r'const PUBLIC_KEY=(.*);',original).group(1))
    template = (release.ROOT/'packaging/remote_telegram_token.html').read_text()
    public = home.parent.parent/'telegram-connection/mobile-public'
    public.mkdir(mode=0o700,exist_ok=True)
    out = public/'index.html'
    rendered = template.replace('__PUBLIC_JWK__',json.dumps(jwk)).replace('__BINDING__',json.dumps(binding,ensure_ascii=False))
    out.write_text(rendered)
    # Only the opaque binding is placed on the public page. The target path and owner stay private.
    if request['binding']['profile_home'] in rendered or request['binding']['owner_user_id'] in rendered:
        raise PermissionError('private_binding_must_not_be_published')
    request.update(mobile_binding=binding,mobile_html=str(out),mobile_html_sha256=release.digest(out))
    release.write(active,request)
    release.write(Path(request['key_file']).parent/'request.json',request)
    print(json.dumps({'html':str(out),'sha256':release.digest(out),'expires_at':binding['expires_at'],'private_owner_or_path_included':False}))


def accept(path):
    selected, home, _ = selected_test()
    active = release.ROOT.parent/'.operator/remote-telegram-current.json'
    request = release.read(active)
    case = home.parent.parent/'telegram-connection'
    if request['consumed'] or (case/'connection.json').exists() or (case/'apply-started.json').exists():
        raise PermissionError('transfer_already_consumed_or_prior_effects_require_inspection')
    if request['binding']['instance_id'] != selected['instance_id'] or request['binding']['profile_home'] != str(home/'data'):
        raise PermissionError('selected_TEST_changed')
    if path.stat().st_size>8192:
        raise ValueError('oversized_encrypted_attachment')
    token = None
    # Exactly two operator-created transports may share this one recipient key; no binding is inferred.
    bindings = [request['binding']]
    if request.get('mobile_binding'):
        bindings.append(request['mobile_binding'])
    for binding in bindings:
        try:
            token = decrypt(path.read_text(),binding,Path(request['key_file']).read_bytes())
            break
        except ValueError:
            continue
    if token is None:
        raise ValueError('encrypted_transfer_invalid_expired_or_for_another_instance')
    url = request['form_url']
    form = release.read(case/'form.json')
    parsed = urllib.parse.urlsplit(url)
    if url!=form['url'] or parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path!='/':
        raise PermissionError('local_intake_binding_changed')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(url,timeout=10) as response:
            page = response.read(16384).decode()
        csrf = re.search(r'name="csrf" value="([A-Za-z0-9_-]+)"',page).group(1)
        body = urllib.parse.urlencode({'csrf':csrf,'token':token}).encode()
        post = urllib.request.Request(url+'save',data=body,headers={'Origin':url.rstrip('/'),
            'Content-Type':'application/x-www-form-urlencoded'})
        with opener.open(post,timeout=100) as response:
            response.read(16384)
    except Exception:
        raise RuntimeError('local_intake_did_not_complete_inspect_effects_before_retry') from None
    result = release.read(case/'connection.json')
    if (result['instance_id']!=selected['instance_id'] or result['username'].lower()!=request['binding']['bot_username']
            or result['owner_user_id']!=request['binding']['owner_user_id']):
        raise PermissionError('saved_connection_binding_mismatch')
    request.update(consumed=True,imported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ciphertext_sha256=release.digest(path),native_connection_receipt=str(case/'connection.json'))
    release.write(active,request)
    release.write(Path(request['key_file']).parent/'request.json',request)
    print(json.dumps({'token_saved_to_TEST':True,'bot_username':result['username'],'production_changed':False}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','prepare-mobile','accept'])
    parser.add_argument('--file',type=Path)
    args = parser.parse_args()
    if args.action=='prepare':
        prepare()
    elif args.action=='prepare-mobile':
        prepare_mobile()
    else:
        if not args.file:
            parser.error('--file required')
        accept(args.file)


if __name__=='__main__':
    main()
