"""Publish one complete neutral candidate; no clobber, stable promotion or production changes."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,tempfile,time
import release_cli as m


def command(argv,**kw):
 p=subprocess.run(argv,capture_output=True,text=True,**kw)
 if p.returncode:raise RuntimeError(p.stderr[-1400:])
 return p.stdout


def api(path,body=None):
 if body is None:return json.loads(command(['gh','api',path]))
 with tempfile.NamedTemporaryFile('w',suffix='.json') as f:
  json.dump(body,f);f.flush();return json.loads(command(['gh','api','--method','POST',path,'--input',f.name]))


def main():
 p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--repo',required=True);p.add_argument('--tag',required=True);p.add_argument('--target',required=True);a=p.parse_args();d=a.directory.resolve();r=m.verify_release(d)
 if r.get('owner_data_included') or r.get('credentials_included') or r.get('historical_patch_chain_required'):raise PermissionError('neutral_integrated_candidate_required')
 subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(m.ROOT/'trust/allowed_signers'),'-I','bnn-release','-n',m.NAMESPACE,'-s',str(d/'QUALIFICATION-SUMMARY.json.sig')],input=(d/'QUALIFICATION-SUMMARY.json').read_bytes(),check=True,capture_output=True)
 summary=m.read(d/'QUALIFICATION-SUMMARY.json')
 if summary.get('archive_sha256')!=r['archive']['sha256']:raise PermissionError('summary_for_different_archive')
 if summary.get('native_installations_passed')!=2:raise PermissionError('two_actual_native_installations_required')
 existing=api('repos/'+a.repo+'/releases?per_page=100&tick='+str(time.time_ns()));matches=[v for v in existing if v['tag_name']==a.tag]
 if len(matches)>1:raise PermissionError('ambiguous_release')
 if matches:release=matches[0]
 else:
  release=api('repos/'+a.repo+'/releases',{'tag_name':a.tag,'target_commitish':a.target,'name':'Hermes BNN 2026.11.1: integrated candidate','body':'Полный нейтральный кандидат для нативной macOS Apple Silicon. Все программы и среды включены; исторические исправления не нужны. Две отдельные нативные установки и 40 проверок выпускной инфраструктуры подтверждены.\n\nСтатус: кандидат, не производственный допуск. Реальные модельные и Telegram-прогоны, исследование, обновление данных и восстановление ещё не подтверждены этой поставкой. Действующий BNN не обновляется автоматически.\n\nСкачайте все части одного архива и следуйте INSTALL.md. Подпись манифеста и суммы проверяются до установки. Внешние аккаунты, ключи и личные данные не включены.','draft':True,'prerelease':True,'make_latest':'false'})
 rid=release['id'];record=d/'PUBLICATION.json';have={v['name']:v for v in release['assets']};confirmed=[]
 def refresh():return {v['name']:v for v in api('repos/'+a.repo+'/releases/'+str(rid)+'/assets?per_page=100&tick='+str(time.time_ns()))}
 def upload(path):
  nonlocal have
  h=m.digest(path);entry=have.get(path.name)
  if entry:
   if entry.get('digest')!='sha256:'+h or entry['size']!=path.stat().st_size:raise PermissionError('existing_asset_differs_do_not_overwrite:'+path.name)
  else:
   attempt=subprocess.run(['gh','release','upload',a.tag,str(path),'--repo',a.repo],capture_output=True,text=True,env={**os.environ,'GODEBUG':'http2client=0'})
   for observation in range(4):
    have=refresh();entry=have.get(path.name)
    if entry and entry.get('digest')=='sha256:'+h:break
    if observation<3:time.sleep(1)
   if not entry or entry.get('digest')!='sha256:'+h:raise RuntimeError('upload_not_confirmed_no_automatic_reupload:'+path.name+':'+attempt.stderr[-500:])
  confirmed.append({'name':path.name,'bytes':path.stat().st_size,'sha256':h,'server_digest_verified':True})
  m.write(record,{'repository':a.repo,'tag':a.tag,'release_id':rid,'draft':True,'assets':confirmed})
 parts=[];work=Path(m.resources()['release_root'])/'.upload-work';work.mkdir(exist_ok=True)
 with (d/r['archive']['name']).open('rb') as stream:
  index=0
  while data:=stream.read(512*1024*1024):
   index+=1;name=r['archive']['name']+f'.part{index:03d}';h=hashlib.sha256(data).hexdigest();parts.append({'name':name,'bytes':len(data),'sha256':h})
   with tempfile.TemporaryDirectory(prefix='part-',dir=work) as temporary:
    path=Path(temporary)/name;path.write_bytes(data);upload(path)
   print(json.dumps({'part':index,'bytes_confirmed':sum(v['bytes'] for v in parts)}),flush=True)
 m.write(d/'PARTS.json',{'archive':r['archive'],'parts':parts,'password_required':False,'old_releases_required':False});m.sign_manifest(d/'PARTS.json',Path(m.resources()['development_root'])/'.operator/keys/release_ed25519')
 (d/'allowed_signers').write_bytes((m.ROOT/'trust/allowed_signers').read_bytes())
 (d/'INSTALL.md').write_text('''# Установка цельного кандидата Hermes BNN\n\nПоддержана нативная macOS 26.5.1 arm64. Это кандидат для испытаний; рабочий экземпляр не заменяйте. Ключи и история не входят.\n\n1. Скачайте RELEASE.json, RELEASE.json.sig, PARTS.json, PARTS.json.sig, allowed_signers и все partNNN. Доверенный allowed_signers дополнительно сверьте с trust/allowed_signers исходного репозитория.\n2. Проверьте подписи:\n\n```sh\nssh-keygen -Y verify -f allowed_signers -I bnn-release -n bnn-release-v1 -s RELEASE.json.sig < RELEASE.json\nssh-keygen -Y verify -f allowed_signers -I bnn-release -n bnn-release-v1 -s PARTS.json.sig < PARTS.json\n```\n\n3. В отдельной пустой папке объедините только части этого выпуска по порядку part001, part002 и далее в файл с именем archive.name из RELEASE.json. Проверьте SHA-256 собранного файла по archive.sha256. На macOS значения читаются через plutil -extract archive.name raw -o - RELEASE.json и plutil -extract archive.sha256 raw -o - RELEASE.json; контрольная сумма вычисляется shasum -a 256 ИМЯ_АРХИВА.\n4. Распакуйте в новую местную папку вне Dropbox/iCloud, прочитайте Hermes-BNN-Full/docs/INSTALL_MACOS.md. При необходимости установите прилагаемую R 4.6.1 через системный установщик.\n5. Запустите bash install.sh из Hermes-BNN-Full. Он проверит весь состав и подписи поставщиков до создания отдельного владельца и состояния. Для внешних инструментов нужен собственный вход.\n\nПроверки моделей, Telegram, исследования, обновления данных и восстановления этой поставкой ещё не закрыты. Номер продукта указан в BNN-PRODUCT.json.\n''')
 for name in ['RELEASE.json','RELEASE.json.sig','PARTS.json','PARTS.json.sig','QUALIFICATION-SUMMARY.json','QUALIFICATION-SUMMARY.json.sig','allowed_signers','INSTALL.md']:upload(d/name)
 command(['gh','release','edit',a.tag,'--repo',a.repo,'--draft=false','--prerelease','--latest=false'])
 done=api('repos/'+a.repo+'/releases/'+str(rid));have=refresh()
 for row in confirmed:
  if have.get(row['name'],{}).get('digest')!='sha256:'+row['sha256']:raise PermissionError('published_digest_changed')
 m.write(record,{'repository':a.repo,'tag':a.tag,'release_id':rid,'draft':done['draft'],'prerelease':done['prerelease'],'url':done['html_url'],'assets':confirmed,'all_server_digests_verified':True,'production_promoted':False})
 print(done['html_url'],flush=True)

if __name__=='__main__':main()
