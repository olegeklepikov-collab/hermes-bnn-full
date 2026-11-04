"""Derived retrieval fragments. Existing document/UDR ledgers remain the authorities."""
import json
import fcntl
import re
import sqlite3
import time
from pathlib import Path
from bn_memory.store import canonical,sha,SENSITIVE
from bn_memory.documents import filehash,current_decoder

class SourceIndex:
    def __init__(self,broker):
        self.broker=broker;self.store=broker.store;self.config=broker.config
        from bn_memory.documents import Documents
        Documents(broker)
        with self.store.db() as db:
            marker=db.execute("SELECT value FROM meta WHERE key='source_fts_contract'").fetchone()
            if not marker or marker[0]!='1':raise RuntimeError('explicit_source_fts_migration_required')
        self._verified={}

    def runs(self):
        if self.config.get('udr_index_enabled',True) is False:return []
        path=self.config.get('udr_host_state');base=self.config.get('udr_workspace')
        if not path or not base:return []
        paths=[Path(path),*[Path(n) for n in self.config.get('native_session_databases',[])]]
        stamps=[]
        for p in paths:
            for q in [p,Path(str(p)+'-wal')]:
                st=q.stat() if q.exists() else None
                stamps.append((str(q),st.st_mtime_ns,st.st_ctime_ns,st.st_size) if st else (str(q),None))
        if getattr(self,'_runs_stamp',None)==stamps:return self._runs_value
        native=set()
        for name in self.config.get('native_session_databases',[]):
            p=Path(name)
            if p.is_symlink() or not p.is_file():continue
            with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
                native.update(x[0] for x in db.execute('SELECT id FROM sessions'))
        p=Path(path)
        if p.is_symlink():raise PermissionError('unsafe_udr_registry')
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
            rows=db.execute('SELECT run_id,original_sid,current_sid FROM research_runs').fetchall()
        result=[(r,old,new) for r,old,new in rows if re.fullmatch(r'r-[a-f0-9]{16}',r) and (old in native or new in native)]
        self._runs_stamp=stamps;self._runs_value=result
        return result

    def scopes(self,sid):
        binding=self.store.binding(sid);allowed=self.store.scopes(binding)
        root=binding
        while root.get('parent'):root=self.store.binding(root['parent'])
        for run,old,new in self.runs():
            if root['sid'] in {old,new}:allowed.append('udr:'+run)
            elif not binding['readonly']:
                try:self.store.safe_file(sid,str(Path(self.config['udr_workspace'])/'bn-research-runs'/run))
                except PermissionError:continue
                allowed.append('udr:'+run)
        return list(dict.fromkeys(allowed))

    @staticmethod
    def regular(path,root):
        path=Path(path);root=Path(root).resolve()
        if not path.is_absolute() or not path.is_relative_to(root):raise PermissionError('source_path_outside_root')
        current=root
        for part in path.relative_to(root).parts:
            current=current/part
            if current.is_symlink():raise PermissionError('source_symlink_denied')
        if not path.is_file():raise FileNotFoundError('source_file_missing')
        return path

    def verified(self,path,digest,root):
        path=self.regular(path,root);st=path.stat();key=(str(path),st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        if self._verified.get(key)!=digest:
            if filehash(path)!=digest:raise ValueError('source_integrity_failed')
            self._verified[key]=digest
        return path

    def authority_root(self,path):
        roots=self.config.get('document_authority_roots',[self.config.get('document_authority_root',str(Path(self.config['state_root'])/'documents'))])
        if not isinstance(roots,list) or not 1<=len(roots)<=32:raise PermissionError('document_authority_roots_invalid')
        for root in roots:
            base=Path(root).resolve()
            if Path(path).is_relative_to(base):return base
        raise PermissionError('source_path_outside_root')

    def unit_path(self,unit):
        meta=json.loads(unit['meta'])
        if unit['kind']=='document':
            from bn_memory.documents import Documents
            with self.store.db() as db:
                row=db.execute('SELECT s.*,c.scope FROM document_sources s JOIN document_corpora c ON c.id=s.corpus WHERE s.id=?',(meta['doc_id'],)).fetchone()
                index=db.execute('SELECT body FROM document_units WHERE doc=? AND unit=?',(meta['doc_id'],meta['unit'])).fetchone()
            if not row or not index or row['scope']!=unit['scope'] or row['sha256']!=meta['source_sha256'] or row['status']!='extracted':raise PermissionError('source_authority_changed')
            row=dict(row)
            if not current_decoder(row):raise PermissionError('source_decoder_stale')
            info=json.loads(index[0]);body=json.loads(row['body'])
            if info['text_sha256']!=unit['version']:raise ValueError('source_unit_changed')
            original=Path(body['snapshot']);unit_file=Path(body['parse_output'])/(str(meta['unit'])+'.txt')
            self.verified(original,row['sha256'],self.authority_root(original))
            return self.verified(unit_file,unit['version'],self.authority_root(unit_file))
        run=meta['run_id']
        if not any(r==run for r,_,_ in self.runs()):raise PermissionError('udr_source_not_native')
        root=Path(self.config['udr_workspace'])/'bn-research-runs'/run
        database=self.regular(root/'corpus.sqlite',root)
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT path,sha256 FROM sources WHERE id=?',(meta['source_id'],)).fetchone()
        if not row or row[1]!=unit['version'] or '..' in Path(row[0]).parts or Path(row[0]).is_absolute():raise PermissionError('udr_source_authority_changed')
        return self.verified(root/row[0],row[1],root)

    def discover(self,sid=None):
        if sid:self.store.writable(sid)
        allowed=set(self.scopes(sid)) if sid else None;units=[]
        with self.store.db() as db:
            rows=db.execute("SELECT s.id,s.sha256,s.body,s.path,s.format,c.id AS corpus,c.scope,u.unit,u.body AS unit_body FROM document_sources s JOIN document_corpora c ON c.id=s.corpus JOIN document_units u ON u.doc=s.id WHERE s.status='extracted' ORDER BY s.id,u.unit").fetchall()
        seen=set()
        rows=sorted(rows,key=lambda r:(not current_decoder(dict(r)),r['id'],r['unit']))
        for row in rows:
            if allowed is not None and row['scope'] not in allowed:continue
            info=json.loads(row['unit_body']);body=json.loads(row['body'])
            identity=body.get('source_path',row['path'])+':'+row['sha256']+':'+str(row['unit'])+':'+info['text_sha256']
            uid='SUN-'+sha(row['scope']+':'+identity)[:32]
            if uid in seen:continue
            seen.add(uid)
            meta={'doc_id':row['id'],'corpus_id':row['corpus'],'unit':row['unit'],'source_sha256':row['sha256'],
                  'source_path':body.get('source_path',row['path']),'locator':info.get('locator'),'visual_required':info.get('visual_required',False)}
            if body.get('origin_reference'):meta['origin_reference']=body['origin_reference']
            state='excluded_fixture' if row['corpus'] in self.config.get('excluded_source_corpora',[]) else 'pending' if current_decoder(dict(row)) else 'excluded_stale_decoder'
            units.append((uid,row['scope'],'document','document:'+row['id']+':'+str(row['unit']),info['text_sha256'],meta,info['characters'],state))
        for run,_,_ in self.runs():
            scope='udr:'+run
            if allowed is not None and scope not in allowed:continue
            root=Path(self.config['udr_workspace'])/'bn-research-runs'/run
            try:database=self.regular(root/'corpus.sqlite',root)
            except FileNotFoundError:continue
            with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:rows=db.execute('SELECT id,path,sha256,chars,url,title,extent FROM sources').fetchall()
            for source,path,digest,total,url,title,extent in rows:
                uid='SUN-'+sha(scope+':'+source+':'+digest)[:32]
                units.append((uid,scope,'udr','udr:'+run+':'+source,digest,
                    {'run_id':run,'source_id':source,'source_sha256':digest,'url':url,'title':title,'extent':extent},total,'pending'))
        with self.store.db() as db:
            for uid,scope,kind,ref,version,meta,total,state in units:
                db.execute('INSERT OR IGNORE INTO semantic_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uid,scope,kind,ref,version,canonical(meta),state,0,0,total,'',time.time()))
                if state=='excluded_stale_decoder':db.execute("UPDATE semantic_units SET state='excluded_stale_decoder' WHERE id=?",(uid,))
                else:
                    db.execute("UPDATE semantic_units SET meta=?,ref=?,state=CASE WHEN state='excluded_stale_decoder' THEN 'pending' ELSE state END WHERE id=?",(canonical(meta),ref,uid))
        return len(units)

    def chunk(self,unit,limit):
        path=self.unit_path(unit)
        # Scan the whole admitted text before exporting any part, including secrets at boundaries.
        previous='';characters=0
        with path.open(encoding='utf-8',newline='') as f:
            for text in iter(lambda:f.read(65536),''):
                if SENSITIVE.search(previous+text):raise PermissionError('sensitive_source_not_embedding')
                previous=text[-1024:];characters+=len(text)
        if characters!=unit['total']:raise ValueError('source_extent_changed')
        pos=unit['chars'];byte=unit['bytes'];chunks=[]
        with path.open('rb') as raw:
            raw.seek(byte)
            import io
            f=io.TextIOWrapper(raw,encoding='utf-8',newline='')
            for _ in range(limit):
                text=f.read(1600)
                if not text:break
                end=pos+len(text);last=byte+len(text.encode());key='SRC-'+sha(unit['id']+':'+str(pos)+':'+sha(text))[:32]
                chunks.append((key,unit['id'],unit['scope'],pos,end,byte,last,sha(text),text,'pending',None));pos=end;byte=last
        with self.store.db() as db:
            for row in chunks:db.execute('INSERT OR IGNORE INTO semantic_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)',row)
            db.execute('UPDATE semantic_units SET chars=?,bytes=?,state=?,updated=? WHERE id=?',(pos,byte,'chunked' if pos==characters else 'pending',time.time(),unit['id']))
        return len(chunks)

    def sync(self,limit=32,sid=None,*,vector=None):
        if type(limit) is not int or not 1<=limit<=64:raise ValueError('source_batch_invalid')
        if vector is not None and type(vector) is not bool:raise ValueError('source_vector_mode_invalid')
        if sid:self.store.writable(sid)
        with (Path(self.config['state_root'])/'source-index.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return {'processed':0,'indexed':0,'busy':True}
            return self._sync(limit,sid,vector=vector)

    def _sync(self,limit=32,sid=None,*,vector=None):
        if sid:self.store.writable(sid)
        scopes=self.scopes(sid) if sid else None;where='';params=[]
        if scopes:where=' AND scope IN ('+','.join('?' for _ in scopes)+')';params=scopes
        used=0;errors=[]
        with self.store.db() as db:units=[dict(r) for r in db.execute("SELECT * FROM semantic_units WHERE state='pending'"+where+' ORDER BY updated LIMIT ?',[*params,limit])]
        for unit in units:
            if used>=limit or getattr(self.broker,'stop_event',None) is not None and self.broker.stop_event.is_set():break
            try:used+=self.chunk(unit,limit-used)
            except Exception as exc:
                with self.store.db() as db:db.execute("UPDATE semantic_units SET state='blocked',reason=? WHERE id=?",(type(exc).__name__+':'+str(exc)[:160],unit['id']))
                errors.append({'unit':unit['id'],'code':str(exc)[:160]})
        from bn_memory.source_queue import eligible,deferred
        with self.store.db() as db:
            if vector is False or vector is None and self.config.get('source_vector_index_enabled',True) is False:
                rows=[dict(r) for r in db.execute("SELECT * FROM semantic_chunks WHERE state='pending'"+where+' LIMIT ?',[*params,limit])];waiting=0
            else:
                rows=eligible(self,db,scopes,limit)
                waiting=deferred(self,db,scopes)
        valid=[]
        for row in rows:
            try:
                with self.store.db() as db:unit=dict(db.execute('SELECT * FROM semantic_units WHERE id=?',(row['unit'],)).fetchone())
                path=self.unit_path(unit)
                with path.open('rb') as f:f.seek(row['byte_begin']);text=f.read(row['byte_end']-row['byte_begin']).decode('utf-8')
                if text!=row['text'] or sha(text)!=row['hash'] or SENSITIVE.search(text):raise PermissionError('fragment_no_longer_admitted')
                if not text.strip():
                    with self.store.db() as db:db.execute("UPDATE semantic_chunks SET state='no_text_vector',receipt=? WHERE id=?",(canonical({'reason':'empty or visual-only unit; original retained; no embedding or reading credit'}),row['id']))
                    continue
                valid.append(row)
            except Exception as exc:
                with self.store.db() as db:db.execute("UPDATE semantic_chunks SET state='blocked',receipt=? WHERE id=?",(canonical({'code':str(exc)[:160]}),row['id']))
                errors.append({'chunk':row['id'],'code':str(exc)[:160]})
        rows=valid
        if vector is False or vector is None and self.config.get('source_vector_index_enabled',True) is False:
            return {'processed':used,'indexed':0,'blocked':errors,'lexical_available':True,'vector_index':'disabled'}
        if rows:
            vectors=self.broker.embedding_many([r['text'] for r in rows],'document')
            records=[{'id':r['id'],'revision':1,'scope':r['scope'],'content_hash':r['hash'],'status':'recorded','vector':v} for r,v in zip(rows,vectors)]
            result=self.broker.worker('zvec','sync_many',{'records':records,'collection_kind':'sources'})
            with self.store.db() as db:
                for row in rows:db.execute("UPDATE semantic_chunks SET state='indexed',receipt=? WHERE id=?",(canonical({'readback_verified':True,'content_hash':row['hash'],'space_id':result.get('space_id'),'projection_target':result.get('projection_target')}),row['id']))
        return {'processed':used,'indexed':len(rows),'blocked':errors,
                'deferred_unsettled_inputs':waiting,'historical_attempts_replayed':False,
                'complete':not waiting and not errors}

    def read_hit(self,sid,item,*,lexical=False):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM semantic_chunks WHERE id=?',(item['id'],)).fetchone()
            if not row:raise PermissionError('source_fragment_missing')
            row=dict(row);unit=dict(db.execute('SELECT * FROM semantic_units WHERE id=?',(row['unit'],)).fetchone())
        if row['scope'] not in self.scopes(sid) or row['state'] not in ({'pending','indexed'} if lexical else {'indexed'}) or row['hash']!=item['content_hash'] or item['revision']!=1:raise PermissionError('source_fragment_outside_scope_or_stale')
        meta=json.loads(unit['meta'])
        if unit['state']=='blocked' or unit['state'].startswith('excluded_'):raise PermissionError('source_unit_not_current')
        if self.store.binding(sid)['readonly']:
            from bn_memory.source_visibility import Visibility
            if unit['kind']!='document':raise PermissionError('child_udr_source_visibility_not_qualified')
            Visibility(self.store).source(sid,meta['source_sha256'])
            with self.store.db() as db:
                grant=db.execute('SELECT 1 FROM document_pending WHERE profile_id=? AND sid=? AND doc=? AND unit=?',
                    (self.store.profile,sid,meta.get('doc_id',''),meta.get('unit',-1))).fetchone()
            if not grant:raise PermissionError('child_source_unit_not_assigned')
        path=self.unit_path(unit)
        with path.open('rb') as f:f.seek(row['byte_begin']);text=f.read(row['byte_end']-row['byte_begin']).decode('utf-8')
        if SENSITIVE.search(text):raise PermissionError('private_source_fragment')
        if sha(text)!=row['hash'] or text!=row['text']:raise ValueError('source_fragment_integrity_failed')
        return {'id':row['id'],'kind':'source','retrieval_kind':'source','scope':row['scope'],'text':text,'content_hash':row['hash'],
                'source_ref':unit['ref'],'source_sha256':meta['source_sha256'],'chars':[row['begin'],row['end']],
                'metadata':meta,'reading_level':'exact_retrieval_fragment','phase_reading_credit':False,'evidence_status':'unreviewed'}

    def read(self,sid,ident,revision=None,*,lexical=None):
        if revision not in (None,1):raise ValueError('source_revision_invalid')
        with self.store.db() as db:row=db.execute('SELECT hash FROM semantic_chunks WHERE id=?',(ident,)).fetchone()
        if not row:raise KeyError('source_fragment_missing')
        if lexical is None:lexical=self.config.get('source_fts_enabled',False)
        return self.read_hit(sid,{'id':ident,'revision':1,'content_hash':row[0]},lexical=lexical)

    def lexical_search(self,sid,query,limit=5,offset=0):
        from bn_memory.source_fts import search
        return search(self,sid,query,limit,offset)

    def validate_context(self,sid,context):
        # Only host-selected physical fragments are validated; arbitrary user quotes gain no authority.
        marker='<BN_MEMORY_CONTEXT sha256="'
        if marker not in context:return
        body=context.split(marker,1)[1].split('\n',1)[1].split('\n</BN_MEMORY_CONTEXT>',1)[0]
        value=json.loads(body)
        for item in value.get('source_fragments',[]):
            current=self.read(sid,item['id'])
            if current['content_hash']!=item['content_hash'] or current['source_sha256']!=item['source_sha256']:
                raise PermissionError('context_source_fragment_stale')

    def status(self,sid=None):
        if sid and self.store.binding(sid)['readonly']:raise PermissionError('child_source_index_aggregate_not_qualified')
        scopes=self.scopes(sid) if sid else None;where=' WHERE scope IN ('+','.join('?' for _ in scopes)+')' if scopes else '';params=scopes or []
        with self.store.db() as db:
            units=[dict(r) for r in db.execute('SELECT state,count(*) AS n,sum(total) AS characters,sum(chars) AS chunked FROM semantic_units'+where+' GROUP BY state',params)]
            chunks=[dict(r) for r in db.execute('SELECT state,count(*) AS n FROM semantic_chunks'+where+' GROUP BY state',params)]
        return {'units':units,'chunks':chunks,'lexical_enabled':self.config.get('source_fts_enabled',False),'vector_index_enabled':self.config.get('source_vector_index_enabled',True),'udr_index_enabled':self.config.get('udr_index_enabled',True),'current_source_bytes_checked_at_query':True,'reading_credit':False,'source_authority':'existing document and UDR ledgers'}
