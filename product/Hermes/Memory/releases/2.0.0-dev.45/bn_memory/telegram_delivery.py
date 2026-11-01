"""Pinned owner-only Bot API transport. No recipient or endpoint comes from a model."""
import hashlib,json
from pathlib import Path
class TelegramDelivery:
    def __init__(self,config):self.config=config;self.rule=config.get('delivery',{})
    def recipient(self):
        from hermes_constants import get_hermes_home
        p=Path(self.rule.get('recipient_file','/not-configured'))
        if not p.is_file():raise PermissionError('owner_delivery_not_configured')
        value=json.loads(p.read_text())
        if value['profile_home']!=str(get_hermes_home().resolve()) or value['profile_home']!=self.config['profile_home']:raise PermissionError('delivery_profile_mismatch')
        if str(value['recipient_user_id'])!=str(self.rule['recipient_user_id']) or value['bot_username'].lower()!=self.rule['bot_username'].lower():raise PermissionError('delivery_recipient_not_pinned')
        return {k:value[k] for k in ['bot_id','bot_username','recipient_user_id','profile_home']}
    def call(self,method,**kwargs):
        import httpx
        token=Path(self.rule['telegram_key_file']).read_text().strip()
        with httpx.Client(timeout=120,trust_env=False,follow_redirects=False) as client:r=client.post('https://api.telegram.org/bot'+token+'/'+method,**kwargs)
        value=r.json()
        if r.status_code!=200 or not value.get('ok'):raise RuntimeError('Telegram_refused_'+str(r.status_code))
        return value['result']
    def preflight(self,size):
        recipient=self.recipient()
        if size>50_000_000:raise PermissionError('telegram_upload_limit_50MB_use_other_approved_transport')
        bot=self.call('getMe')
        if bot['id']!=recipient['bot_id'] or bot['username'].lower()!=recipient['bot_username'].lower():raise PermissionError('telegram_bot_identity_changed')
    def send(self,path,name,caption,size):
        recipient=self.recipient()
        with path.open('rb') as stream:message=self.call('sendDocument',data={'chat_id':recipient['recipient_user_id'],'caption':caption},files={'document':(name,stream,'application/octet-stream')})
        if str(message['chat']['id'])!=recipient['recipient_user_id'] or message['chat']['type']!='private' or message.get('from',{}).get('id')!=recipient['bot_id']:raise PermissionError('telegram_returned_wrong_recipient')
        document=message.get('document',{})
        return {'transport':'telegram_bot_api','bot_id':recipient['bot_id'],'chat_id':str(message['chat']['id']),'message_id':message['message_id'],'file_id':document.get('file_id'),'file_unique_id':document.get('file_unique_id'),'file_size':document.get('file_size'),'file_name':document.get('file_name'),'sent':True,'owner_received':False}
    def verify(self,receipt,expected,size):
        import httpx
        if size>20_000_000:return {'server_bytes_verified':False,'reason':'cloud_getFile_download_limit_20MB','owner_received':False}
        file=self.call('getFile',json={'file_id':receipt['file_id']});token=Path(self.rule['telegram_key_file']).read_text().strip();digest=hashlib.sha256();count=0
        with httpx.Client(timeout=120,trust_env=False,follow_redirects=False) as client:
            with client.stream('GET','https://api.telegram.org/file/bot'+token+'/'+file['file_path']) as response:
                response.raise_for_status()
                for block in response.iter_bytes():digest.update(block);count+=len(block)
        if count!=size or digest.hexdigest()!=expected:raise PermissionError('telegram_download_hash_mismatch')
        return {'server_bytes_verified':True,'received_sha256':digest.hexdigest(),'received_bytes':count,'owner_received':False}
