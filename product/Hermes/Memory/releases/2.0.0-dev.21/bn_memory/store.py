from bn_memory import __version__
"""Owner-scoped primary memory. Derived stores are never authority or instructions."""
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager,closing
from pathlib import Path
from bn_memory import record_metadata

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()

SENSITIVE=re.compile(r'(?i)(?:(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,}|\b[0-9]{8,}:[A-Za-z0-9_-]{25,}|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+)')
PRIVATE={'.env','auth.json','mcp-tokens.json','credentials.json','.git','node_modules','authority'}

class Store:
    def __init__(self, root, config):
        self.root=Path(root);self.config=config;self.path=self.root/'memory.sqlite'
        from bn_memory.namespace import configuration
        self.namespace=configuration(config);self.profile=self.namespace['profile_id']

    @contextmanager
    def db(self):
        if self.path.is_symlink():raise PermissionError('unsafe_primary_store')
        if not self.path.is_file():raise RuntimeError('primary_memory_unavailable')
        c=sqlite3.connect(self.path,timeout=3);c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA synchronous=FULL')
            if c.execute('SELECT value FROM meta WHERE key=\'schema\'').fetchone()[0]!='2':raise RuntimeError('memory_schema_not_supported')
            from bn_memory.namespace import verify
            verify(c,self.namespace)
            yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()

    def initialize(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.exists():raise FileExistsError('primary_store_already_exists')
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO meta VALUES('schema','2');
            CREATE TABLE records(id TEXT NOT NULL,revision INTEGER NOT NULL,scope TEXT NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,concepts TEXT NOT NULL,PRIMARY KEY(id,revision));
            CREATE TABLE current(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,FOREIGN KEY(id,revision) REFERENCES records(id,revision));
            CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,content,tokenize='unicode61');
            CREATE TABLE operations(key TEXT PRIMARY KEY,input_hash TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE outbox(id TEXT NOT NULL,revision INTEGER NOT NULL,backend TEXT NOT NULL,status TEXT NOT NULL,receipt TEXT,PRIMARY KEY(id,revision,backend));
            CREATE TABLE audit(seq INTEGER PRIMARY KEY,event TEXT NOT NULL,sid_hash TEXT NOT NULL,record_id TEXT,revision INTEGER,at REAL NOT NULL);
            CREATE TABLE budget(day TEXT PRIMARY KEY,bytes INTEGER NOT NULL);
            CREATE TABLE vectors(id TEXT NOT NULL,revision INTEGER NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL,PRIMARY KEY(id,revision));
            ''')
            from bn_memory.control_schema import install as create
            from bn_memory.namespace import install as install_namespace
            create(c,'sessions')
            install_namespace(c,self.namespace)
            record_metadata.install(c)
            from bn_memory.source_visibility import install as install_visibility
            install_visibility(c)
            from bn_memory.compute import install as install_compute
            install_compute(c)
            from bn_memory.admission import install as install_admission
            install_admission(c)
            from bn_memory.checkpoint import install as install_checkpoint
            install_checkpoint(c)
            from bn_memory.action_control import install as install_actions
            install_actions(c)
            from bn_memory.working import install as install_working
            install_working(c)
            from bn_memory.envelope import install as install_envelope
            install_envelope(c,self.namespace['owner_id'])
            from bn_memory.packet import install as install_packet
            install_packet(c)
            from bn_memory.source_fts import install as install_source_fts
            install_source_fts(c)
            from bn_memory.embedding_contract import install as install_embeddings
            install_embeddings(c)
            c.commit()
        self.path.chmod(0o600)

    def session_hash(self,sid):
        return sha(canonical([self.namespace['owner_id'],self.profile,sid]))

    def bind(self,sid,parent='',project=None,subagent=False):
        if not isinstance(sid,str) or not sid or len(sid)>512:raise PermissionError('native_session_required')
        with self.db() as c:
            old=c.execute('SELECT * FROM sessions WHERE sid=? AND profile_id=?',(sid,self.profile)).fetchone()
            if old:
                if parent and old['parent']!=parent:raise PermissionError('parent_binding_conflict')
                return dict(old)
            if parent:
                p=c.execute('SELECT * FROM sessions WHERE sid=? AND profile_id=?',(parent,self.profile)).fetchone()
                if not p:raise PermissionError('parent_memory_binding_required')
                values=(sid,p['project'],p['task'],parent,1)
            else:
                if subagent:raise PermissionError('child_binding_required')
                project=project or self.config['default_project']
                if project not in self.config['projects']:raise PermissionError('registered_project_required')
                values=(sid,project,'task-'+self.session_hash(sid)[:24],None,0)
            c.execute('INSERT INTO sessions(sid,project,task,parent,readonly,role,profile_id) VALUES(?,?,?,?,?,?,?)',(*values,'unassigned' if parent else 'parent',self.profile))
        return self.binding(sid)

    def assign(self,parent_sid,child_sid,role,purpose,assignment_id):
        self.writable(parent_sid)
        child=self.binding(child_sid)
        if child['parent']!=parent_sid or not child['readonly']:raise PermissionError('direct_child_assignment_required')
        if role not in record_metadata.ROLES or role=='parent':raise ValueError('child_role_invalid')
        if not isinstance(purpose,str) or not purpose.strip() or not isinstance(assignment_id,str) or not assignment_id:raise ValueError('assignment_contract_required')
        with self.db() as c:
            c.execute('UPDATE sessions SET role=?,purpose=?,assignment_id=?,context=NULL,turn=NULL WHERE sid=? AND profile_id=?',(role,purpose,assignment_id,child_sid,self.profile))
            from bn_memory.working import inherit
            inherit(c,self.profile,parent_sid,child_sid)
        return self.binding(child_sid)

    def binding(self,sid):
        with self.db() as c:
            r=c.execute('SELECT * FROM sessions WHERE sid=? AND profile_id=?',(sid,self.profile)).fetchone()
            if not r:raise PermissionError('native_memory_binding_required')
            parent=r['parent'];seen={sid};depth=0
            while parent:
                if parent in seen or depth>=16:raise PermissionError('memory_parent_lineage_invalid')
                seen.add(parent);depth+=1;p=c.execute('SELECT * FROM sessions WHERE sid=? AND profile_id=?',(parent,self.profile)).fetchone()
                if not p or p['project']!=r['project'] or p['task']!=r['task']:raise PermissionError('parent_memory_scope_changed')
                parent=p['parent']
        result=dict(r)
        if result['readonly'] and result['assignment_id'] and self.config.get('w3_enabled'):
            from bn_memory.assignment_resources import read
            resources=read(self,result);result['_assigned_records']=resources['records']
            result['_assigned_sources']=sorted({v[key] for kind in ['files','code','documents','library'] for v in resources[kind].values() for key in ['sha256','file_sha256'] if key in v})
        return result

    @staticmethod
    def scopes(binding):return ['owner','project:'+binding['project'],'task:'+binding['task']]

    def scope(self,sid,level):
        b=self.binding(sid)
        if level not in {'owner','project','task'}:raise ValueError('scope_level_invalid')
        return 'owner' if level=='owner' else level+':'+b[level]

    def writable(self,sid):
        b=self.binding(sid)
        if b['readonly']:raise PermissionError('child_memory_is_read_only')
        return b

    def select_project(self,sid,project):
        binding=self.writable(sid)
        if project not in self.config['projects']:raise PermissionError('registered_project_required')
        with self.db() as c:
            c.execute('UPDATE sessions SET project=?,context=NULL,turn=NULL WHERE sid=? AND profile_id=?',(project,sid,self.profile))
            if binding['project']!=project:
                c.execute('DELETE FROM working_bindings WHERE profile_id=? AND sid=?',(self.profile,sid))
        return {'project':project,'registered_projects':list(self.config['projects'])}

    def record(self,sid,args):
        self.writable(sid)
        metadata=record_metadata.attributes(args)
        content=args['content'];source=args['source_ref'];concepts=args.get('concepts',[])
        if not isinstance(content,str) or not 0<len(content.encode())<=8192:raise ValueError('split_record_required')
        if not isinstance(source,str) or not 0<len(source)<=1024:raise ValueError('source_ref_required')
        if SENSITIVE.search(content+'\n'+source):raise ValueError('secret_not_memory')
        if args['kind'] not in {'preference','decision','note','source','candidate'}:raise ValueError('memory_kind_invalid')
        if not isinstance(concepts,list) or len(concepts)>12 or any(not isinstance(x,str) or not 0<len(x)<=80 or SENSITIVE.search(x) for x in concepts):raise ValueError('concepts_invalid')
        scope=self.scope(sid,args.get('scope','task'));key=args['request_id']
        if not isinstance(key,str) or not 0<len(key)<=128:raise ValueError('request_id_required')
        op=sha(canonical([self.namespace['owner_id'],self.profile,sid,key]));ih=sha(canonical(args));rid=args.get('id') or 'MEM-'+sha(canonical([self.namespace['owner_id'],self.profile,sid,scope,key]))[:24]
        if not re.fullmatch(r'MEM-[a-f0-9]{24}',rid):raise ValueError('record_id_invalid')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM operations WHERE key=?',(op,)).fetchone()
            if old:
                if old['input_hash']!=ih:raise ValueError('idempotency_conflict')
                return {**json.loads(old['result']),'duplicate':True}
            old=c.execute('SELECT r.* FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision WHERE r.id=?',(rid,)).fetchone()
            if old and (old['scope']!=scope or old['scope'] not in self.scopes(self.binding(sid))):raise PermissionError('record_outside_scope')
            expected=args.get('expected_revision',0)
            if type(expected) is not int or expected!=(old['revision'] if old else 0):raise ValueError('revision_conflict')
            revision=expected+1
            c.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,revision,scope,args['kind'],content,sha(content),source,'recorded',time.time(),canonical(concepts)))
            record_metadata.insert(c,rid,revision,metadata)
            from bn_memory.source_visibility import Visibility
            Visibility(self).record(c,self.binding(sid),metadata)
            c.execute('INSERT INTO current VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision',(rid,revision))
            c.execute('DELETE FROM search WHERE id=?',(rid,));c.execute('INSERT INTO search VALUES(?,?)',(rid,content))
            for backend in ['agentmemory','graphiti','zvec']:c.execute('INSERT INTO outbox VALUES(?,?,?,\'pending\',NULL)',(rid,revision,backend))
            from bn_memory.envelope import write as write_envelope
            write_envelope(c,dict(c.execute('SELECT * FROM records WHERE id=? AND revision=?',(rid,revision)).fetchone()),self.namespace['owner_id'],self.binding(sid),metadata,'record')
            result={'id':rid,'revision':revision,'content_hash':sha(content),'scope':scope,'status':'recorded','evidence_status':'unreviewed','source_ref':source}
            c.execute('INSERT INTO operations VALUES(?,?,?)',(op,ih,canonical(result)))
            c.execute('UPDATE sessions SET context=NULL,turn=NULL WHERE task=(SELECT task FROM sessions WHERE sid=? AND profile_id=?)',(sid,self.profile))
            c.execute('INSERT INTO audit(event,sid_hash,record_id,revision,at) VALUES(?,?,?,?,?)',('record',self.session_hash(sid),rid,revision,time.time()))
        return result

    def read(self,sid,rid,revision=None):
        b=self.binding(sid)
        with self.db() as c:
            if revision is None:r=c.execute('SELECT r.* FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision WHERE r.id=?',(rid,)).fetchone()
            else:r=c.execute('SELECT * FROM records WHERE id=? AND revision=?',(rid,revision)).fetchone()
            current=c.execute('SELECT r.status,r.revision FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision WHERE r.id=?',(rid,)).fetchone()
        if not r or r['scope'] not in self.scopes(b):raise PermissionError('record_unavailable_in_scope')
        if not current or current['status']=='retracted':raise PermissionError('record_retracted')
        r=dict(r)
        if b['readonly'] and self.config.get('w3_enabled'):
            from bn_memory.assignment_resources import record
            record(self,sid,rid,r['revision'],r['content_hash'])
        if sha(r['content'])!=r['content_hash']:raise RuntimeError('primary_content_hash_mismatch')
        with self.db() as c:
            metadata=record_metadata.read(c,rid,r['revision'])
            current_metadata=record_metadata.read(c,rid,current['revision'])
        record_metadata.enforce(b,metadata)
        record_metadata.enforce(b,current_metadata)
        from bn_memory.source_visibility import Visibility
        visibility=Visibility(self)
        dependency_status='current'
        with self.db() as c:
            try:
                visibility.record(c,b,metadata)
                visibility.record(c,b,current_metadata)
            except PermissionError:
                if b['readonly']:raise
                dependency_status='stale_or_unavailable'
        from bn_memory.embedding_contract import space
        from bn_memory.envelope import read as read_envelope
        with self.db() as c:
            r['envelope']=read_envelope(c,rid,r['revision'])
            from bn_memory.envelope import projections
            r['projections']=projections(c,rid,expected_space=space(self.config)['space_id'],expected_targets=self.config.get('projection_targets'))
        r.update(metadata)
        if metadata.get('source_dependencies'):r['dependency_status']=dependency_status
        r['concepts']=json.loads(r['concepts']);r['evidence_status']='unreviewed';return r

    def retract(self,sid,rid,expected):
        binding=self.writable(sid)
        if type(expected) is not int or expected<1:raise ValueError('revision_conflict')
        from bn_memory.envelope import write as write_envelope
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT r.* FROM records r JOIN current u ON u.id=r.id AND u.revision=r.revision WHERE r.id=?',(rid,)).fetchone()
            if not old or old['scope'] not in self.scopes(binding):raise PermissionError('record_unavailable_in_scope')
            if old['status']=='retracted' and old['revision']==expected+1:
                return {'id':rid,'revision':old['revision'],'status':'retracted','duplicate':True,'historical_ledger_retained':True}
            if old['revision']!=expected or old['status']=='retracted':raise ValueError('revision_conflict')
            revision=expected+1;row=dict(old);row.update(revision=revision,status='retracted',created=time.time())
            c.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(row[key] for key in ['id','revision','scope','kind','content','content_hash','source','status','created','concepts']))
            metadata=record_metadata.read(c,rid,expected)
            record_metadata.insert(c,rid,revision,metadata)
            c.execute('UPDATE current SET revision=? WHERE id=?',(revision,rid))
            c.execute('DELETE FROM search WHERE id=?',(rid,))
            for backend in ['agentmemory','graphiti','zvec']:
                c.execute("INSERT INTO outbox VALUES(?,?,?,'pending',NULL)",(rid,revision,backend))
            write_envelope(c,row,self.namespace['owner_id'],binding,metadata,'retract')
            c.execute('UPDATE sessions SET context=NULL,turn=NULL')
            c.execute('INSERT INTO audit(event,sid_hash,record_id,revision,at) VALUES(?,?,?,?,?)',('retract',self.session_hash(sid),rid,revision,time.time()))
        return {'id':rid,'revision':revision,'status':'retracted','derived_deletion':'pending','historical_ledger_retained':True}

    def local_search(self,sid,query,limit=5,offset=0):
        b=self.binding(sid);scope=self.scopes(b)
        if not isinstance(query,str) or len(query)>1024 or SENSITIVE.search(query):raise ValueError('query_invalid')
        if type(limit) is not int or not 1<=limit<=10 or type(offset) is not int or offset<0:raise ValueError('page_invalid')
        tokens=re.findall(r'\w+',query,re.UNICODE)[:24];expr=' OR '.join('"'+x+'"' for x in tokens)
        with self.db() as c:
            sql='SELECT r.* FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision '
            params=[]
            if expr:sql+='JOIN search ON search.id=r.id WHERE search MATCH ? AND ';params.append(expr)
            else:sql+='WHERE '
            role_sql,role_params=record_metadata.search_filter(b)
            if b['readonly']:
                from bn_memory.source_visibility import Visibility
                c.create_function('bn_dependencies_visible',1,lambda raw:Visibility(self).visible(c,b,raw))
                role_sql+=' AND bn_dependencies_visible(m.attributes)=1'
            sql+='r.status=\'recorded\' AND r.scope IN (?,?,?)'+role_sql+' ORDER BY '+('bm25(search),' if expr else '')+'r.created DESC LIMIT ? OFFSET ?'
            rows=c.execute(sql,[*params,*scope,*role_params,limit+1,offset]).fetchall()
        return {'records':[self.read(sid,r['id']) for r in rows[:limit]],'has_more':len(rows)>limit,'next_offset':offset+limit if len(rows)>limit else None,'scope':scope,'backend':'sqlite_fts5'}

    def retrieval_basis(self,sid):
        b=self.binding(sid)
        fields={key:b[key] for key in ['profile_id','sid','project','task','parent','readonly','role','assignment_id']}
        with self.db() as c:
            fields['source_policy_generation']=c.execute('SELECT count(*) FROM source_policies').fetchone()[0]
            fields['data_epoch']=c.execute("SELECT COALESCE(MAX(a.seq),0) FROM audit a JOIN records r ON a.record_id=r.id AND a.revision=r.revision WHERE a.event IN ('record','retract') AND r.scope IN (?,?,?)",self.scopes(b)).fetchone()[0]
        return sha(canonical(fields))

    def vector_candidates(self,sid):
        b=self.binding(sid);before=self.retrieval_basis(sid)
        if not b['readonly']:raise PermissionError('child_vector_candidate_binding_required')
        with self.db() as c:
            role_sql,params=record_metadata.search_filter(b)
            from bn_memory.source_visibility import Visibility
            c.create_function('bn_dependencies_visible',1,lambda raw:Visibility(self).visible(c,b,raw))
            rows=c.execute("SELECT r.id,r.revision,r.content_hash,r.scope FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision WHERE r.status='recorded' AND r.scope IN (?,?,?)"+role_sql+' AND bn_dependencies_visible(m.attributes)=1 ORDER BY r.id',self.scopes(b)+params).fetchall()
        if self.retrieval_basis(sid)!=before:raise PermissionError('vector_primary_basis_changed')
        return {'records':[dict(r) for r in rows],'basis':before}

    def context(self,sid,query,turn):
        from bn_memory.context_v2 import build
        return build(self,sid,query,turn)

    def status(self,sid):
        b=self.binding(sid)
        with self.db() as c:
            scope=self.scopes(b)
            from bn_memory.embedding_contract import space
            expected_space=space(self.config)['space_id']
            pending=[dict(x) for x in c.execute('''SELECT o.backend,
                CASE WHEN o.backend='zvec' AND o.status='indexed' AND
                  CASE WHEN json_valid(o.receipt) THEN COALESCE(json_extract(o.receipt,'$.space_id'),'') ELSE '' END != ?
                  THEN 'needs_space_rebuild' ELSE o.status END AS status,count(*) AS count
                FROM outbox o JOIN current u ON o.id=u.id AND o.revision=u.revision
                JOIN records r ON r.id=o.id AND r.revision=o.revision
                WHERE r.scope IN (?,?,?) GROUP BY o.backend,2''',[expected_space,*scope])]
            count=c.execute('SELECT count(*) FROM current u JOIN records r ON r.id=u.id AND r.revision=u.revision WHERE r.scope IN (?,?,?)',scope).fetchone()[0]
            if self.config.get('projection_targets'):
                from collections import Counter
                actual=Counter()
                for item in c.execute('SELECT o.backend,o.status,o.receipt FROM outbox o JOIN current u ON o.id=u.id AND o.revision=u.revision JOIN records r ON r.id=o.id AND r.revision=o.revision WHERE r.scope IN (?,?,?)',scope):
                    backend,status,raw=item;value=json.loads(raw or '{}')
                    if status=='indexed' and value.get('projection_target')!=self.config['projection_targets'].get(backend):status='needs_target_rebind'
                    actual[backend,status]+=1
                pending=[{'backend':key[0],'status':key[1],'count':number} for key,number in sorted(actual.items())]
        if b['readonly']:
            with self.db() as c:
                role_sql,role_params=record_metadata.search_filter(b)
                from bn_memory.source_visibility import Visibility
                c.create_function('bn_dependencies_visible',1,lambda raw:Visibility(self).visible(c,b,raw))
                count=c.execute("SELECT count(*) FROM current u JOIN records r ON r.id=u.id AND r.revision=u.revision JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision WHERE r.status='recorded' AND r.scope IN (?,?,?)"+role_sql+' AND bn_dependencies_visible(m.attributes)=1',[*scope,*role_params]).fetchone()[0]
                pending=[]
        projects=self.config['projects'] if not b['readonly'] and self.config.get('owner_project_reads',False) else {b['project']:self.config['projects'][b['project']]}
        return {'version':__version__,'binding':{k:b[k] for k in ['profile_id','project','task','readonly']},'owner_id':self.namespace['owner_id'],'primary':'sqlite','records':count,'derived':pending,'cognee':'not_needed_for_current_scope','embedding_contract':{'version':2,'legacy_cache_active':False,'old_space_indexes_automatically_promoted':False},'raw_database_access':False,'readable_projects':projects,'project_file_paths':'absolute within readable_projects or relative to binding.project; reading another project does not switch memory scope'}

    def safe_file(self,sid,relative):
        b=self.binding(sid);root=Path(self.config['projects'][b['project']]).resolve();p=Path(relative)
        if '..' in p.parts:raise PermissionError('file_outside_public_project')
        if p.is_absolute():
            roots=[root]
            if (not b['readonly'] and self.config.get('owner_project_reads',False)) or b['readonly'] and self.config.get('w3_enabled'):
                roots.extend(Path(v).resolve() for v in self.config['projects'].values())
            root=next((r for r in roots if p.is_relative_to(r)),None)
            if root is None:raise PermissionError('file_outside_public_project')
            p=p.relative_to(root)
        if any(x in PRIVATE or x.startswith('.env') for x in p.parts):raise PermissionError('file_outside_public_project')
        target=root/p
        # Inspect lexical components before resolution; even an in-root alias is not a source.
        current=root
        for part in p.parts:
            current=current/part
            if current.is_symlink():raise PermissionError('symlink_file_denied')
        if not target.resolve().is_relative_to(root):raise PermissionError('file_outside_public_project')
        if b['readonly']:
            if self.config.get('w3_enabled'):
                from bn_memory.assignment_resources import read,file
                selected=read(self,b);kind='files' if str(target) in selected['files'] else 'code'
                file(self,sid,target,kind)
            from bn_memory.source_visibility import Visibility,hash_file
            Visibility(self).source(sid,hash_file(target))
        return root,target

    def snapshot(self,destination):
        destination=Path(destination)
        if destination.exists():raise FileExistsError('snapshot_exists')
        with self.db() as src,closing(sqlite3.connect(destination)) as dst:src.backup(dst)
        destination.chmod(0o600);return {'file':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
