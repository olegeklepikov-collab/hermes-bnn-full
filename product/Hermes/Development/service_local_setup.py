"""Pin only this owner's native Zotero; persistent consent remains in Zotero UI."""
import json,time
from pathlib import Path
import httpx,psutil
from service_auth import ROOT,save
def zotero(authorize=False):
 cfg=json.loads((ROOT/'Memory/settings.json').read_text());state=Path(cfg['zotero_root']);profile=state/'profile'
 markers=[state/'process.json',state.parent/'zotero.pid.json']
 marker=next((p for p in markers if p.exists()),None)
 if marker is None:raise PermissionError('start_the_documented_own_native_Zotero_profile_first')
 process=json.loads(marker.read_text());args=psutil.Process(process['pid']).cmdline()
 if str(profile) not in args or not any(str(ROOT/'Zotero/app') in arg for arg in args):raise PermissionError('own_Zotero_process_identity_required')
 previous=json.loads((state/'identity.json').read_text()) if (state/'identity.json').exists() else {}
 url=previous.get('base_url','http://127.0.0.1:65030/api/')
 if not url.startswith('http://127.0.0.1:') or not url.endswith('/api/'):raise PermissionError('pinned_local_Zotero_API_required')
 from service_lifecycle import quiescent,stop_for_cutover,restart_previous
 quiescent(cfg);lifecycle=stop_for_cutover()
 with httpx.Client(timeout=180,trust_env=False,follow_redirects=False) as client:
  response=client.get(url,headers={'Zotero-API-Version':'3'});response.raise_for_status();sid=response.headers.get('Zotero-Server-ID')
  if not sid:raise PermissionError('Zotero_server_identity_not_returned')
  if previous.get('server_id') and previous['server_id']!=sid:raise PermissionError('Zotero_instance_changed_repin_requires_explicit_operator_review')
  identity={**previous,'base_url':url,'server_id':sid,'profile':str(profile),'data':str(state/'data'),'library_scope':'users/0','account_email':previous.get('account_email'),'sync_account_bound':False,'import_roots':list(cfg['projects'].values()),'output_root':str(ROOT/'Services/software/Zotero/exports')}
  for p in [state/'identity.json',ROOT/'Services/software/Zotero/config/identity.json']:save(p,identity)
  if authorize:
   print('В Zotero подтвердите постоянный доступ только к этой отдельной библиотеке. Ключ не выводится.',flush=True)
   native=profile/'localAPIKeys.json';existing=[]
   if native.exists():existing=[r for r in json.loads(native.read_text()).get('keys',[]) if r.get('appName')=='Hermes BNN — research services' and r.get('remember')]
   if len(existing)==1:grant=existing[0]
   else:
    response=client.post(url+'local/authorize',json={'appName':'Hermes BNN — research services'},headers={'Zotero-API-Version':'3','Zotero-Server-ID':sid});response.raise_for_status();grant=response.json()
   if not grant.get('remember') or not grant.get('key'):raise PermissionError('persistent_local_Zotero_consent_required')
   grant['server_id']=sid
   for p in [state/'authorization.json',ROOT/'Services/software/Zotero/config/authorization.json']:save(p,grant)
 import sys;sys.path.insert(0,cfg['package_root'])
 if 'zotero' in cfg.get('backend_policy',{}).get('allow',{}):
  from bn_memory.backend_policy import resource_hash
  cfg['backend_policy']['allow']['zotero']['resource_sha256']=resource_hash(cfg,'zotero');save(ROOT/'Memory/settings.json',cfg)
 restart_previous(lifecycle)
 return {'own_native_instance_pinned':True,'local_write_authorization_saved':authorize,'external_account_authorized':False,'credentials_printed':False}
