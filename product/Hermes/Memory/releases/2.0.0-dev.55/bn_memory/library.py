"""Pinned local Zotero identity; native API writes, common isolated decoder for every attachment."""
import hashlib,json,re
from pathlib import Path
from urllib.parse import unquote,urlsplit
from bn_memory.store import canonical,sha,SENSITIVE

class Library:
    def __init__(self,broker):
        self.broker=broker;self.store=broker.store;self.root=Path(broker.config['zotero_root'])
        self.identity=json.loads((self.root/'identity.json').read_text())
        self.data=(self.root/'data').resolve()
    def key(self,key):
        if not isinstance(key,str) or not re.fullmatch('[A-Z0-9]{8}',key):raise ValueError('zotero_key_invalid')
        return key
    def request(self,path,method='GET',data=None,headers=None):
        import httpx
        base=self.identity['base_url'];parsed=urlsplit(base)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port!=64030:raise PermissionError('zotero_pinned_endpoint_invalid')
        hdr={'Zotero-API-Version':'3','Zotero-Server-ID':self.identity['server_id'],**(headers or {})}
        if method!='GET':
            value=json.loads((self.root/'authorization.json').read_text())
            if not value.get('remember') or value['server_id']!=self.identity['server_id']:raise PermissionError('zotero_native_authorization_mismatch')
            hdr['Zotero-API-Key']=value['key']
        with httpx.Client(timeout=45,trust_env=False,follow_redirects=False) as client:r=client.request(method,base+path,json=data,headers=hdr)
        if r.headers.get('Zotero-Server-ID')!=self.identity['server_id']:raise PermissionError('zotero_instance_changed')
        if r.status_code!=302:r.raise_for_status()
        return r
    def path(self,key):
        key=self.key(key);r=self.request('users/0/items/'+key+'/file');given=urlsplit(r.headers.get('Location',''))
        if r.status_code!=302 or given.scheme!='file':raise PermissionError('zotero_existing_local_file_required')
        from bn_memory.path_relocation import operating_path
        path=operating_path(self.broker.config,unquote(given.path))
        if not path.is_relative_to(self.data) or any(p.is_symlink() for p in [path,*path.parents] if p.is_relative_to(self.data)) or not path.is_file():raise PermissionError('zotero_attachment_outside_owned_copy')
        return path
    def dispatch(self,sid,args):
        action=args['action'];child=self.store.binding(sid)['readonly'];key=args.get('key')
        if child and action not in {'item','children','attachment'}:raise PermissionError('child_library_action_not_qualified')
        expected=None
        if child:
            if not self.broker.config.get('w3_enabled'):raise PermissionError('child_library_scope_not_qualified')
            from bn_memory.assignment_resources import require
            expected=require(self.store,sid,'library',self.key(key))
        if action=='search':
            q=args.get('query','')
            if not isinstance(q,str) or len(q)>1024 or SENSITIVE.search(q):raise ValueError('library_query_invalid')
            from urllib.parse import urlencode
            r=self.request('users/0/items?'+urlencode({'q':q,'qmode':'everything','limit':args.get('limit',20),'start':args.get('offset',0)}));value=r.json()
            return {'items':value,'library_version':r.headers.get('Last-Modified-Version'),'total':r.headers.get('Total-Results'),'completeness':'enumerated_page','offset':args.get('offset',0),'reading_level':'bibliographic_metadata','evidence_status':'unreviewed'}
        if action in {'item','children','collections'}:
            path='users/0/collections' if action=='collections' else 'users/0/items/'+self.key(key)+('/children' if action=='children' else '')
            r=self.request(path);value=r.json();fingerprint=sha(canonical(value))
            if child and action=='item' and fingerprint!=expected['sha256']:raise PermissionError('assigned_library_version_changed')
            if child and action=='children':
                from bn_memory.assignment_resources import require
                for item in value:require(self.store,sid,'library',self.key(item['key']))
            from bn_memory.source_visibility import Visibility
            Visibility(self.store).source(sid,fingerprint)
            if SENSITIVE.search(canonical(value)):raise PermissionError('sensitive_library_metadata')
            return {'data':value,'version':r.headers.get('Last-Modified-Version'),'source_sha256':fingerprint,'server_id':self.identity['server_id'],'reading_level':'bibliographic_metadata','evidence_status':'unreviewed'}
        if action=='attachment':
            path=self.path(key)
            from bn_memory.documents import filehash
            value=filehash(path)
            from bn_memory.source_visibility import Visibility
            Visibility(self.store).source(sid,value)
            return {'key':key,'path':str(path),'sha256':value,'bytes':path.stat().st_size,'reading_level':'file_metadata_only','common_parser_required':True}
        if action=='parse':
            self.store.writable(sid)
            from bn_memory.intake import addressed_unit
            result=addressed_unit(self.broker,sid,str(self.path(key)),args['request_id'],unit=args.get('unit',0))
            result.pop('text',None);return result
        if action=='export':
            style=args.get('format','ris')
            if style not in {'ris','bibtex','csljson'}:raise ValueError('library_export_format_invalid')
            r=self.request('users/0/items/'+self.key(key)+'?format='+style)
            return {'text':r.text,'format':style,'key':key,'sha256':hashlib.sha256(r.content).hexdigest(),'reading_level':'exported_metadata','claims_accepted':False}
        raise ValueError('library_action_invalid')
