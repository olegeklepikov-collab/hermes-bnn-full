"""Loopback-only credential intake for the selected, qualified TEST instance.

The bot token travels in POST/stdin, never arguments, receipts or console output.
This operator helper does not change the immutable distribution or start a gateway.
"""
import argparse
import copy
import datetime
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import release_cli as release


def validate_input(username, token, forbidden=()):
    name = username.lstrip('@').lower()
    if not re.fullmatch(r'[a-z0-9_]{5,32}', name) or not name.endswith('bot'):
        raise ValueError('invalid_bot_username')
    if name in {v.lstrip('@').lower() for v in forbidden}:
        raise PermissionError('existing_bot_preserved')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{30,}', token):
        raise ValueError('invalid_token_syntax')
    return name


def bot_call(token, method):
    request = urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method, data=b'', method='POST')
    # Do not inherit proxies, follow redirects, or expose exception URLs containing the token.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=25) as response:
            value = json.load(response)
    except Exception:
        raise ConnectionError('telegram_validation_failed') from None
    if not value.get('ok'):
        raise PermissionError('telegram_refused')
    return value['result']


def selected_test():
    selected = release.read(release.ROOT.parent/'.operator/environments.json')['test']
    base = Path(release.resources()['test_root']).resolve()
    install = Path(selected['installation']).resolve()
    if not install.is_relative_to(base):
        raise PermissionError('qualified_TEST_root_required')
    qualification = release.read(selected['qualification'])
    if qualification['environment'] != 'test' or qualification['instance_id'] != selected['instance_id']:
        raise PermissionError('TEST_qualification_mismatch')
    home = install/'Hermes'
    if release.read(home/'state/bootstrap.json')['instance_id'] != selected['instance_id']:
        raise PermissionError('TEST_instance_changed')
    return selected, home, qualification


def intake_api(home):
    import yaml
    app = yaml.safe_load((home/'data/config.yaml').read_text())
    settings = app['plugins']['entries']['bn-common-memory']['settings']
    library = Path(settings['intake_library']).resolve()
    if not library.is_relative_to(home.resolve()) or settings['config_file'] != str(home/'Memory/settings.json'):
        raise PermissionError('TEST_intake_library_binding_changed')
    package = Path(release.read(home/'Memory/settings.json')['package_root']).resolve()
    if not package.is_relative_to(home.resolve()):
        raise PermissionError('TEST_memory_package_binding_changed')
    sys.path.insert(0,str(package));sys.path.insert(0,str(library))
    from bnn_intake import deployment, bootstrap
    return deployment, bootstrap


def delivery_change(before, after, home, bot, owner):
    expected = copy.deepcopy(before)
    expected['delivery'].update(recipient_user_id=owner, bot_username=bot['username'],
        profile_home=str(home/'data'), telegram_key_file=str(home/'private/telegram.token'),
        recipient_file=str(home/'private/telegram-recipient.json'))
    if after != expected:
        raise PermissionError('unrelated_settings_change_cannot_be_enrolled')


def apply_native(home, case):
    deployment, bootstrap = intake_api(home)
    path = home/'Memory/settings.json'
    # Enrolment is an operator operation. Preserve the mandatory exact-settings check.
    bootstrap.verify_deployment(home/'data',path,release.read(path))
    with deployment.stopped(home,home/'data',True):
        before = release.read(path)
        target = case/'before-intake-deployment.json'
        target.write_bytes((home/'data/intake-deployment.json').read_bytes());target.chmod(0o600)
        _apply_native(home,case)
        after = release.read(path)
        bot = release.read(home/'private/telegram-recipient.json')
        delivery_change(before,after,home,{'username':bot['bot_username']},str(bot['recipient_user_id']))
        deployment.enroll(home,path)
        bootstrap.verify_deployment(home/'data',path,after)


def repair_intake(home,case):
    """Recover only the exact Telegram delta of a saved, witnessed adapter attempt."""
    import hashlib
    import hmac
    deployment, bootstrap = intake_api(home)
    connection = release.read(case/'connection.json')
    if connection['profile_home'] != str(home/'data') or not connection['native_save_completed']:
        raise PermissionError('completed_TEST_connection_required')
    path = home/'Memory/settings.json'
    before = release.read(case/'before-memory-settings.json')
    after = release.read(path)
    delivery_change(before,after,home,connection,connection['owner_user_id'])
    envelope = release.read(home/'data/intake-deployment.json')
    value = envelope['deployment']
    from bnn_intake.storage import canonical
    expected = hmac.new(Path(after['host_key']).read_bytes(),canonical(value).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(envelope['signature'],expected) or value['settings_sha256']!=release.digest(case/'before-memory-settings.json'):
        raise PermissionError('original_intake_enrolment_not_the_witnessed_preimage')
    with deployment.stopped(home,home/'data',True):
        witness = deployment.preservation_witness(Path(after['state_root'])/'memory.sqlite')
        target = case/'before-intake-deployment.json'
        if not target.exists():
            target.write_bytes((home/'data/intake-deployment.json').read_bytes());target.chmod(0o600)
        deployment.enroll(home,path)
        bootstrap.verify_deployment(home/'data',path,after)
        if witness!=deployment.preservation_witness(Path(after['state_root'])/'memory.sqlite'):
            raise PermissionError('runtime_history_changed_during_enrolment')
        release.write(case/'intake-enrolment-repair.json',{'exact_Telegram_delta_only':True,
            'native_deployment_verified':True,'history_and_resources_preserved':True,'controls_disabled':False,
            'settings_sha256':release.digest(path),'production_changed':False})


def _apply_native(home, case):
    """Invoked with the selected instance's own Python and clean environment."""
    from hermes_cli.config import save_env_value, require_env_writable, get_env_value, write_platform_config_field
    payload = json.load(sys.stdin)
    token, bot, owner = payload['token'], payload['bot'], payload['owner']
    cfg_path = home/'Memory/settings.json'
    cfg = release.read(cfg_path)
    paths = [home/'private/telegram.token', home/'private/telegram-recipient.json']
    if cfg['profile_home'] != str(home/'data') or any(p.exists() or p.is_symlink() for p in paths):
        raise PermissionError('new_TEST_connection_required')
    if get_env_value('TELEGRAM_BOT_TOKEN'):
        raise PermissionError('existing_TEST_credential_preserved')
    if paths[0].parent.is_symlink():
        raise PermissionError('private_directory_must_not_be_a_symlink')
    for key in ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_ALLOWED_USERS', 'TELEGRAM_HOME_CHANNEL',
                'TELEGRAM_ALLOW_ALL_USERS', 'GATEWAY_ALLOW_ALL_USERS']:
        require_env_writable(key, 'set')
    # Preserve the exact pre-connection state before the first mutation.
    for name, path in [('memory-settings.json', cfg_path), ('config.yaml', home/'data/config.yaml')]:
        target = case/('before-'+name)
        target.write_bytes(path.read_bytes()); target.chmod(0o600)
    previous_env = home/'data/.env'
    if previous_env.exists():
        target = case/'before-env'
        target.write_bytes(previous_env.read_bytes()); target.chmod(0o600)
    release.write(case/'before-state.json', {'env_existed':previous_env.exists(), 'gateway_started_by_adapter':False})
    release.write(case/'apply-started.json', {'profile_home':str(home/'data'), 'completed':False})
    os.umask(0o077)
    paths[0].parent.mkdir(mode=0o700, exist_ok=True)
    with paths[0].open('x') as stream:
        stream.write(token+'\n'); stream.flush(); os.fsync(stream.fileno())
    recipient = {'bot_id':bot['id'], 'bot_username':bot['username'],
                 'recipient_user_id':owner, 'profile_home':str(home/'data')}
    release.write(paths[1], recipient)
    save_env_value('TELEGRAM_BOT_TOKEN', token)
    save_env_value('TELEGRAM_ALLOWED_USERS', owner)
    save_env_value('TELEGRAM_HOME_CHANNEL', owner)
    save_env_value('TELEGRAM_ALLOW_ALL_USERS', 'false')
    save_env_value('GATEWAY_ALLOW_ALL_USERS', 'false')
    write_platform_config_field('telegram', 'enabled', True)
    cfg['delivery'].update(recipient_user_id=owner, bot_username=bot['username'],
                           profile_home=str(home/'data'), telegram_key_file=str(paths[0]),
                           recipient_file=str(paths[1]))
    release.write(cfg_path, cfg)
    for path in [*paths, home/'data/.env', cfg_path]:
        path.chmod(0o600)
    if get_env_value('TELEGRAM_BOT_TOKEN') != token or get_env_value('TELEGRAM_ALLOWED_USERS') != owner:
        raise RuntimeError('native_credential_readback_failed')


def serve(args):
    selected, home, qualification = selected_test()
    name = validate_input(args.bot, '123456:'+'X'*32, args.forbid)
    if not re.fullmatch(r'[1-9]\d*', args.owner):
        raise ValueError('numeric_owner_required')
    case = home.parent.parent/'telegram-connection'
    if case.exists():
        raise FileExistsError('existing_connection_attempt_requires_inspection')
    case.mkdir(mode=0o700)
    csrf = secrets.token_urlsafe(32)
    state = {'saved':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, text, content_type='text/html; charset=utf-8'):
            data = text.encode()
            self.send_response(status)
            for key, value in [('Content-Type', content_type), ('Content-Length', str(len(data))),
                               ('Cache-Control','no-store'), ('X-Content-Type-Options','nosniff'),
                               ('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'")]:
                self.send_header(key,value)
            self.end_headers(); self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') == '127.0.0.1:'+str(self.server.server_port)

        def do_GET(self):
            if not self.valid_host() or self.path != '/':
                return self.reply(404, 'Not found')
            if state['saved']:
                return self.reply(200, '<p>Токен сохранён в Hermes BNN TEST. Форму можно закрыть.</p>')
            self.reply(200, '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Hermes BNN TEST</title>'
                '<h1>Подключение @'+html.escape(name)+'</h1><p>Только тестовая среда. Доступ: '+args.owner+'</p>'
                '<form method="post" action="/save"><input type="hidden" name="csrf" value="'+csrf+'">'
                '<label>Токен из BotFather <input name="token" type="password" autocomplete="off" required></label>'
                '<button type="submit">Проверить и сохранить в TEST</button></form></html>')

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = 'http://127.0.0.1:'+str(self.server.server_port)
            if not self.valid_host() or self.path != '/save' or origin not in (None, expected):
                return self.reply(403, 'Запрос отклонён')
            if self.headers.get('Content-Type','').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.reply(415, 'Неподдерживаемый запрос')
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 1 <= size <= 4096:
                    raise ValueError()
                fields = urllib.parse.parse_qs(self.rfile.read(size).decode(), strict_parsing=True)
                if not hmac.compare_digest(fields.get('csrf',[''])[0], csrf):
                    return self.reply(403, 'Запрос отклонён')
                if state['saved'] or (case/'apply-started.json').exists():
                    return self.reply(409, 'Повторное сохранение остановлено. Требуется проверка состояния.')
                token = fields['token'][0].strip()
                validate_input(name, token, args.forbid)
                bot = bot_call(token, 'getMe')
                if bot.get('username','').lower() != name:
                    return self.reply(400, 'Токен принадлежит другому боту. Ничего не сохранено.')
                if bot_call(token, 'getWebhookInfo').get('url'):
                    return self.reply(409, 'Бот уже подключён через webhook. Ничего не изменено.')
                # Avoid forwarding the operator's account environment into TEST.
                env = release.clean_environment(Path(selected['home']))
                env.update(HERMES_HOME=str(home/'data'), HERMES_BNN_ROOT=str(home),
                           PYTHONPATH=str(home/'hermes-agent'), PYTHONDONTWRITEBYTECODE='1')
                completed = subprocess.run([str(home/'hermes-agent/venv/bin/python'), '-B', str(Path(__file__).resolve()),
                    '--apply-home', str(home), '--apply-case', str(case)],
                    input=json.dumps({'token':token, 'bot':bot, 'owner':args.owner}), env=env,
                    cwd=home, text=True, capture_output=True, timeout=60)
                if completed.returncode:
                    # Never expose subprocess stderr: a third party may include a credential in it.
                    raise RuntimeError('native_save_failed')
                receipt = {'contract':'BNNTestTelegramConnectionV1', 'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'instance_id':selected['instance_id'], 'archive_sha256':qualification['archive_sha256'],
                    **{k:v for k,v in bot.items() if k in ('id','username','is_bot')}, 'owner_user_id':args.owner,
                    'profile_home':str(home/'data'), 'credential_permissions':'0600', 'native_save_completed':True,
                    'gateway_started':False, 'incoming_message_verified':False, 'file_delivery_verified':False,
                    'production_changed':False, 'adapter_sha256':release.digest(__file__)}
                release.write(case/'connection.json',receipt)
                state['saved'] = True
                self.reply(200,'<h1>Токен сохранён в Hermes BNN TEST</h1><p>Откройте <a href="https://t.me/'+name+'">@'+name+'</a> и нажмите Start. Затем сообщите: «Сохранено».</p>')
                threading.Thread(target=self.server.shutdown,daemon=True).start()
            except (ValueError, KeyError):
                self.reply(400,'Проверьте полный токен из BotFather. Значение не отображается и не записывается в журнал.')
            except Exception:
                self.reply(502,'Проверка или сохранение не завершены. Сообщите об ошибке оператору; токен в чат не отправляйте.')

    with HTTPServer(('127.0.0.1',args.port), Handler) as server:
        release.write(case/'form.json',{'url':'http://127.0.0.1:'+str(server.server_port)+'/', 'pid':os.getpid(),
            'bot_username':name,'owner_user_id':args.owner,'profile_home':str(home/'data'),'loopback_only':True,'credentials_included':False})
        print(json.dumps(release.read(case/'form.json')),flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot'); parser.add_argument('--owner'); parser.add_argument('--forbid',action='append',default=[])
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--apply-home',type=Path); parser.add_argument('--apply-case',type=Path)
    parser.add_argument('--repair-intake',action='store_true')
    args = parser.parse_args()
    if args.apply_home:
        selected, home, _ = selected_test()
        if args.apply_home.resolve() != home or args.apply_case.resolve() != home.parent.parent/'telegram-connection':
            raise PermissionError('TEST_scope_changed')
        if args.repair_intake:
            repair_intake(home,args.apply_case)
        else:
            apply_native(home, args.apply_case)
    else:
        if not args.bot or not args.owner:
            parser.error('--bot and --owner required')
        serve(args)


if __name__ == '__main__':
    main()
