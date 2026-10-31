"""Loopback-only user-operated service key entry, without credential logging."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs
import json,secrets
import requests
from service_auth import apply_key,save,ROOT,BASE

PORT=64142
ORIGIN='http://127.0.0.1:'+str(PORT)

def serve():
    nonce=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,code,body):
            raw=body.encode();self.send_response(code)
            for k,v in {'Content-Type':'text/html; charset=utf-8','Content-Length':str(len(raw)),'Cache-Control':'no-store',
                'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
                # HTML POST under no-referrer sends Origin:null. Preserve the exact
                # local Origin while external links still use rel=noreferrer.
                'Referrer-Policy':'same-origin','X-Content-Type-Options':'nosniff'}.items():self.send_header(k,v)
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path!='/':return self.reply(404,'Не найдено')
            if self.headers.get('Host')!='127.0.0.1:'+str(PORT):return self.reply(403,'Недопустимый адрес')
            state=[]
            reg=json.loads((ROOT/'Services/registry.private.json').read_text())
            for name in ['tinyfish','synapse']:
                entry=next(e for e in reg['services'] if e['service']==name)
                state.append(name+': '+('ключ сохранён; фактические проверки см. в отчёте' if entry.get('credential_present') and not entry.get('connection_hold') else 'ожидается ключ'))
            body='''<html lang="ru"><meta charset="utf-8"><title>Hermes BNN: ключи сервисов</title>
<style>body{font:18px system-ui;max-width:780px;margin:40px auto;padding:20px}input,select,button{font:inherit;padding:12px;margin:12px 0;box-sizing:border-box;width:100%}small{color:#555}</style>
<h1>Hermes BNN: защищённое подключение</h1><p>Ключ будет проверен только у выбранного поставщика и сохранён в отдельном BNN. Он не передаётся в чат и не записывается в журнал.</p>
<p><a href="https://agent.tinyfish.ai/home" rel="noreferrer">TinyFish</a>: нажмите Copy API key и вставьте существующий ключ. Новый ключ создавать не требуется.</p>
<p><a href="https://www.synapse.org/" rel="noreferrer">Synapse</a>: войдите в свой аккаунт, откройте Account Settings → Personal Access Tokens. Используйте отдельный токен Hermes BNN с правами view и download, без modify и authorize. <a href="https://docs.synapse.org/synapse-docs/managing-your-account" rel="noreferrer">Официальная инструкция</a>.</p>
<form method="post"><input type="hidden" name="csrf" value="'''+nonce+'''">
<label>Поставщик<select name="provider"><option value="tinyfish">TinyFish</option><option value="synapse">Synapse.org</option></select></label>
<label>Ключ или персональный токен<input name="key" type="password" required autocomplete="off"></label>
<button>Проверить и сохранить в BNN</button></form><p>'''+ '<br>'.join(state)+'''</p><small>Покупки, пополнение счёта и изменение подписок не выполняются. Сохранение ключа не означает завершённую проверку всех инструментов.</small></html>'''
            self.reply(200,body)
        def do_POST(self):
            if self.headers.get('Host')!='127.0.0.1:'+str(PORT) or self.headers.get('Origin')!=ORIGIN:return self.reply(403,'Недопустимый источник')
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=32768:raise ValueError()
                body=parse_qs(self.rfile.read(size).decode());provider=body.get('provider',[''])[0];key=body.get('key',[''])[0].strip()
                if provider not in {'tinyfish','synapse'} or not secrets.compare_digest(body.get('csrf',[''])[0],nonce) or not 16<=len(key)<=16384 or any(c.isspace() for c in key):raise ValueError()
                url,header=('https://agent.tinyfish.ai/v1/wallet',{'X-API-Key':key}) if provider=='tinyfish' else ('https://repo-prod.prod.sagebase.org/repo/v1/userProfile',{'Authorization':'Bearer '+key})
                with requests.Session() as client:
                    client.trust_env=False
                    r=client.get(url,headers=header,timeout=(5,20),allow_redirects=False)
                if r.status_code!=200:return self.reply(400,'<meta charset="utf-8"><h1>Поставщик не подтвердил доступ</h1><p>Проверьте ключ и права. Значение не сохранено. <a href="/">Вернуться</a></p>')
                result=apply_key(provider,key)
                save(BASE/('protected-key-'+provider+'-status.json'),{'provider':provider,'saved':True,'authentication_http':200,'secret_logged':False})
                self.reply(200,'<meta charset="utf-8"><h1>Ключ проверен и сохранён</h1><p>Сообщите в рабочем чате название сохранённого сервиса. <a href="/">К следующему сервису</a></p>')
            except ValueError:self.reply(400,'Проверьте выбранный сервис и поле ключа')
            except Exception:self.reply(503,'<meta charset="utf-8">Сохранение не завершено. Значение ключа не выводилось; сообщите о сбое в рабочем чате.')
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()

if __name__=='__main__':serve()
