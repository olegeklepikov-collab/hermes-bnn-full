"""Immutable owned result files; scoped delivery is independent of Research/Foundation."""
import hashlib,json,os,re,secrets,time
from pathlib import Path
from bn_memory.store import canonical,sha,SENSITIVE

class Artifacts:
    def __init__(self,broker):
        self.broker=broker;self.store=broker.store;self.cfg=broker.config
        self.root=Path(self.cfg['state_root'])/'artifacts';self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS result_artifacts(profile_id TEXT,id TEXT,body TEXT,PRIMARY KEY(profile_id,id))')
            db.execute('CREATE TABLE IF NOT EXISTS artifact_requests(profile_id TEXT,sid TEXT,id TEXT,input_hash TEXT,artifact_id TEXT,PRIMARY KEY(profile_id,sid,id))')
            db.execute('CREATE TABLE IF NOT EXISTS result_deliveries(profile_id TEXT,id TEXT,sid TEXT,artifact_id TEXT,request_id TEXT,recipient_hash TEXT,state TEXT,body TEXT,PRIMARY KEY(profile_id,id))')
    def secrets(self):
        values=[]
        for name in ['host_key','voyage_key_file','neo4j_password_file','agentmemory_key_file']:
            if self.cfg.get(name):values.append(Path(self.cfg[name]).read_bytes().strip())
        path=Path(self.cfg.get('delivery',{}).get('telegram_key_file',self.root/'no-key'))
        if path.is_file():values.append(path.read_bytes().strip())
        auth=Path(self.cfg.get('profile_home',''))/'auth.json'
        def collect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in {'access_token','refresh_token'} and isinstance(item,str):values.append(item.encode())
                    else:collect(item)
            elif isinstance(value,list):
                for item in value:collect(item)
        if auth.is_file():collect(json.loads(auth.read_text()))
        zotero=Path(self.cfg.get('zotero_root',self.root/'no-library'))/'authorization.json'
        if zotero.is_file():values.append(json.loads(zotero.read_text())['key'].encode())
        for entry in self.cfg.get('research_providers',{}).get('providers',{}).values():
            values.append(Path(entry['key_file']).read_bytes().strip())
        if self.cfg.get('service_integration'):
            from bn_memory.service_engine import private_values
            values.extend(v.encode() for v in private_values(self.cfg))
        return [v for v in values if len(v)>=16]
    def sensitive(self,data,values):
        if any(v in data for v in values) or SENSITIVE.search(data.decode('utf-8','replace')):raise PermissionError('secret_material_not_deliverable')
    def _get(self,sid,identifier):
        self.store.writable(sid)
        with self.store.db() as db:row=db.execute('SELECT body FROM result_artifacts WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
        if not row:raise PermissionError('artifact_not_owned')
        body=json.loads(row[0])
        if body['source_project'] not in self.cfg['projects']:raise PermissionError('artifact_project_not_registered')
        return body
    def view(self,body):
        result={k:v for k,v in body.items() if k!='snapshot'}
        from bn_memory.path_relocation import operating_path
        actual=str(operating_path(self.cfg,body['source_path']))
        if actual!=body['source_path']:result.update(operating_source_path=actual,original_source_path_preserved=True)
        return result
    def register(self,sid,args):
        self.store.writable(sid);request=args['request_id'];fingerprint=sha(canonical(args))
        with self.store.db() as db:old=db.execute('SELECT input_hash,artifact_id FROM artifact_requests WHERE profile_id=? AND sid=? AND id=?',(self.store.profile,sid,request)).fetchone()
        if old:
            if old[0]!=fingerprint:raise ValueError('artifact_request_input_conflict')
            body=self._get(sid,old[1]);self.verify(body);return {**self.view(body),'duplicate':True,'source_version':'registered immutable snapshot; current source not reread'}
        root,path=self.store.safe_file(sid,args['path'])
        if path.suffix.lower() not in {'.md','.txt','.csv','.tsv','.json','.pdf','.png','.jpg','.jpeg'}:raise PermissionError('result_file_type_not_qualified')
        values=self.secrets();temporary=self.root/('prepare-'+secrets.token_hex(16));fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            before=os.fstat(fd)
            if not __import__('stat').S_ISREG(before.st_mode):raise PermissionError('result_must_be_regular_file')
            checksum=hashlib.sha256();size=0;tail=b'';overlap=max([8192]+[len(v) for v in values])
            out=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(out,'wb') as target,os.fdopen(fd,'rb',closefd=False) as source:
                while block:=source.read(1024*1024):
                    self.sensitive(tail+block,values);checksum.update(block);size+=len(block);target.write(block);tail=(tail+block)[-overlap:]
                target.flush();os.fsync(target.fileno())
            after=os.fstat(fd)
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise PermissionError('result_changed_during_registration')
            digest=checksum.hexdigest()
            if args.get('expected_sha256') not in (None,digest):raise PermissionError('result_hash_mismatch')
            identifier='ART-'+sha(canonical([self.store.profile,str(path),digest]))[:24];snapshot=self.root/(identifier+path.suffix.lower())
            project=max((k for k,v in self.cfg['projects'].items() if path.is_relative_to(Path(v).resolve())),key=lambda k:len(self.cfg['projects'][k]))
            body={'artifact_id':identifier,'source_path':str(path),'source_project':project,'bytes':size,'sha256':digest,'snapshot':str(snapshot),
                'authority':'owner_registered_project','ready_for_delivery':True,'content_evidence_status':'unreviewed','registered_at':time.time(),'file_name':path.name,'original_bytes_modified':False}
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE');existing=db.execute('SELECT body FROM result_artifacts WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
                if existing:body=json.loads(existing[0]);temporary.unlink()
                else:temporary.replace(snapshot);snapshot.chmod(0o400);db.execute('INSERT INTO result_artifacts VALUES(?,?,?)',(self.store.profile,identifier,canonical(body)))
                db.execute('INSERT INTO artifact_requests VALUES(?,?,?,?,?)',(self.store.profile,sid,request,fingerprint,identifier))
            self.verify(body)
            return self.view(body)
        finally:
            os.close(fd)
            if temporary.exists():temporary.unlink()
    def verify(self,body):
        from bn_memory.path_relocation import operating_path
        p=operating_path(self.cfg,body['snapshot'])
        if p.is_symlink() or not p.is_relative_to(self.root) or not p.is_file():raise PermissionError('immutable_result_missing')
        with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=body['sha256'] or p.stat().st_size!=body['bytes']:raise PermissionError('immutable_result_changed')
        return p
    def status(self,sid,identifier):
        body=self._get(sid,identifier);self.verify(body)
        with self.store.db() as db:deliveries=[{'delivery_id':r[0],'state':r[1],'receipt':json.loads(r[2])} for r in db.execute('SELECT id,state,body FROM result_deliveries WHERE profile_id=? AND artifact_id=?',(self.store.profile,identifier))]
        return {**self.view(body),'deliveries':deliveries,'sent':any(d['state'] in {'sent','server_verified','owner_confirmed'} for d in deliveries),'received_by_owner':any(d['state']=='owner_confirmed' for d in deliveries)}
    def deliver(self,sid,args):
        body=self._get(sid,args['artifact_id']);path=self.verify(body)
        if args.get('expected_sha256') not in (None,body['sha256']):raise PermissionError('delivery_expected_hash_mismatch')
        from bn_memory.telegram_delivery import TelegramDelivery
        transport=TelegramDelivery(self.cfg);recipient=transport.recipient()
        caption=args.get('caption','Готовый документ. Выводы и пределы проверки указаны внутри файла.')
        self.sensitive(caption.encode(),self.secrets())
        if len(caption.encode('utf-16-le'))//2>1024:raise ValueError('caption_exceeds_transport_bound')
        fingerprint=sha(canonical(recipient));identifier='DEL-'+sha(canonical([self.store.profile,body['artifact_id'],fingerprint]))[:24]
        def prior(row):
            if row[2]!=fingerprint:raise PermissionError('delivery_recipient_changed')
            if row[0] in {'sending','unknown'}:raise PermissionError('delivery_outcome_unknown_do_not_resend')
            return {'delivery_id':identifier,'state':row[0],'receipt':json.loads(row[1]),'duplicate':True,'new_sends':0}
        with self.store.db() as db:old=db.execute('SELECT state,body,recipient_hash FROM result_deliveries WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
        if old:return prior(old)
        transport.preflight(body['bytes'])
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT state,body,recipient_hash FROM result_deliveries WHERE profile_id=? AND id=?',(self.store.profile,identifier)).fetchone()
            if old:return prior(old)
            db.execute('INSERT INTO result_deliveries VALUES(?,?,?,?,?,?,?,?)',(self.store.profile,identifier,sid,body['artifact_id'],args['request_id'],fingerprint,'sending',canonical({'artifact_sha256':body['sha256'],'caption_sha256':sha(caption),'recipient':recipient,'sent':False})))
        try:
            receipt=transport.send(path,body['file_name'],caption,body['bytes'])
            with self.store.db() as db:db.execute('UPDATE result_deliveries SET state=?,body=? WHERE profile_id=? AND id=?',('sent',canonical(receipt),self.store.profile,identifier))
        except Exception as exc:
            with self.store.db() as db:db.execute("UPDATE result_deliveries SET state='unknown' WHERE profile_id=? AND id=?",(self.store.profile,identifier))
            raise PermissionError('delivery_not_confirmed:'+type(exc).__name__)
        try:
            verified=transport.verify(receipt,body['sha256'],body['bytes'])
            receipt={**receipt,**verified}
            if verified['server_bytes_verified']:
                with self.store.db() as db:db.execute('UPDATE result_deliveries SET state=?,body=? WHERE profile_id=? AND id=?',('server_verified',canonical(receipt),self.store.profile,identifier))
        except Exception:receipt={**receipt,'server_bytes_verified':False,'verification_pending':True}
        return {'delivery_id':identifier,'state':'server_verified' if receipt.get('server_bytes_verified') else 'sent','receipt':receipt,'received_by_owner':False}
    def create(self,sid,args):
        from bn_memory.artifact_create import create
        return create(self,sid,args)
    def dispatch(self,sid,args):
        if args['action']=='create':return self.create(sid,args)
        if args['action']=='register':return self.register(sid,args)
        if args['action']=='status':return self.status(sid,args['artifact_id'])
        if args['action']=='send':return self.deliver(sid,args)
        raise ValueError('artifact_action_invalid')
