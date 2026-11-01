"""Byte-identity source policies and explicit derivative closure. No model-side grants."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from bn_memory import record_metadata


def install(db):
    db.execute('''CREATE TABLE source_policies(
        sha256 TEXT NOT NULL, revision INTEGER NOT NULL, policy TEXT NOT NULL,
        policy_hash TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL,
        PRIMARY KEY(sha256,revision))''')
    db.execute("INSERT INTO meta VALUES('source_visibility_contract','1')")
    from bn_memory.source_policy_scope import install as install_scope
    install_scope(db)


def digest(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise ValueError('source_sha256_invalid')
    return value


def dependencies(value):
    if not isinstance(value,list) or len(value)>128:
        raise ValueError('split_source_dependencies_required')
    result=[]
    for item in value:
        if not isinstance(item,dict):raise ValueError('source_dependency_invalid')
        if item.get('kind')=='source' and set(item)=={'kind','sha256'}:
            digest(item['sha256'])
        elif item.get('kind')=='record' and set(item)=={'kind','id','revision','content_hash'}:
            if not re.fullmatch('MEM-[a-f0-9]{24}',str(item['id'])) or type(item['revision']) is not int or item['revision']<1:
                raise ValueError('record_dependency_invalid')
            digest(item['content_hash'])
        else:raise ValueError('source_dependency_invalid')
        if item in result:raise ValueError('duplicate_source_dependency')
        result.append(dict(item))
    return result


def read_file(path, *, max_bytes=None):
    """Verify the opened regular file, not an earlier path lookup. Preserve CRLF."""
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):raise PermissionError('regular_source_file_required')
        if max_bytes is not None and before.st_size>max_bytes:raise ValueError('split_file_required')
        chunks=[];h=hashlib.sha256();size=0
        while True:
            part=os.read(fd,1024*1024)
            if not part:break
            size+=len(part)
            if max_bytes is not None and size>max_bytes:raise ValueError('split_file_required')
            h.update(part);chunks.append(part)
        after=os.fstat(fd);current=path.stat(follow_symlinks=False)
        stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if stamp(before)!=stamp(after) or stamp(after)!=stamp(current):raise PermissionError('source_changed_during_read')
        return b''.join(chunks),h.hexdigest()
    finally:os.close(fd)


def hash_file(path):
    """Streaming classification of any regular source size; no content in CLI output."""
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):raise PermissionError('regular_source_file_required')
        h=hashlib.sha256()
        while part:=os.read(fd,1024*1024):h.update(part)
        after=os.fstat(fd);current=Path(path).stat(follow_symlinks=False)
        stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if stamp(before)!=stamp(after) or stamp(after)!=stamp(current):raise PermissionError('source_changed_during_read')
        return h.hexdigest()
    finally:os.close(fd)


class Visibility:
    def __init__(self,store):self.store=store

    def verify_snapshot(self,path,sha256):
        """Do not rescan a thousand-page original for every addressed text page."""
        p=Path(path);s=p.stat(follow_symlinks=False)
        if not stat.S_ISREG(s.st_mode):raise PermissionError('regular_source_file_required')
        key=(str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        cache=getattr(self.store,'_verified_source_bytes',{})
        if cache.get(key)!=sha256:
            if hash_file(p)!=digest(sha256):raise PermissionError('document_snapshot_integrity_failed')
            if len(cache)>1024:cache={}
            cache[key]=sha256;self.store._verified_source_bytes=cache

    def policy(self,db,sha256):
        row=db.execute('SELECT * FROM source_policies WHERE sha256=? ORDER BY revision DESC LIMIT 1',(digest(sha256),)).fetchone()
        if not row:return {'visibility':record_metadata.attributes({})['visibility'],'source_dependencies':[]},0
        if hashlib.sha256(row['policy'].encode()).hexdigest()!=row['policy_hash']:raise RuntimeError('source_policy_integrity_failed')
        return json.loads(row['policy']),row['revision']

    def closure(self,db,binding,items, *, require_registered=False,track=False):
        stack=[(item,()) for item in dependencies(items)];seen=set();count=0
        while stack:
            item,ancestors=stack.pop();key=record_metadata.canonical(item)
            if key in ancestors:raise PermissionError('cyclic_source_dependencies')
            if key in seen:continue
            seen.add(key);count+=1
            if count>256:raise PermissionError('split_dependency_closure_required')
            if item['kind']=='source':
                if '_assigned_sources' in binding and item['sha256'] not in binding['_assigned_sources']:raise PermissionError('source_not_assigned_to_native_child')
                policy,revision=self.policy(db,item['sha256'])
                if track:
                    from bn_memory.source_policy_scope import remember
                    remember(db,binding,item['sha256'],revision,policy)
                if require_registered and not revision:raise PermissionError('source_policy_required')
            else:
                if '_assigned_records' in binding:
                    selected=binding['_assigned_records'].get(item['id'])
                    if not selected or selected['revision']!=item['revision'] or selected['content_hash']!=item['content_hash']:raise PermissionError('dependency_not_assigned_to_native_child')
                row=db.execute('SELECT r.* FROM records r JOIN current u ON u.id=r.id AND u.revision=r.revision WHERE r.id=?',(item['id'],)).fetchone()
                if (not row or row['status']!='recorded' or row['revision']!=item['revision']
                        or row['content_hash']!=item['content_hash'] or hashlib.sha256(row['content'].encode()).hexdigest()!=item['content_hash']):
                    raise PermissionError('record_dependency_stale_or_revoked')
                if binding['readonly'] and row['scope'] not in self.store.scopes(binding):raise PermissionError('dependency_outside_scope')
                policy=record_metadata.read(db,row['id'],row['revision'])
            record_metadata.enforce(binding,policy)
            children=dependencies(policy.get('source_dependencies',[]))
            stack.extend((child,(*ancestors,key)) for child in children)

    def source(self,sid,sha256):
        b=self.store.binding(sid)
        with self.store.db() as db:self.closure(db,b,[{'kind':'source','sha256':sha256}],track=True)

    def revise(self,sha256,expected_revision,visibility,reason,source_dependencies=None):
        """Operator API only. Never advertised or dispatched to a model."""
        digest(sha256)
        if type(expected_revision) is not int or expected_revision<0:raise ValueError('source_policy_revision_required')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1024:raise ValueError('source_policy_reason_required')
        policy={'visibility':record_metadata.attributes({'visibility':visibility})['visibility'],
                'source_dependencies':dependencies([] if source_dependencies is None else source_dependencies)}
        raw=record_metadata.canonical(policy)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            _,revision=self.policy(db,sha256)
            if revision!=expected_revision:raise ValueError('source_policy_revision_conflict')
            db.execute('INSERT INTO source_policies VALUES(?,?,?,?,?,?)',(sha256,revision+1,raw,hashlib.sha256(raw.encode()).hexdigest(),reason,time.time()))
            # Detect cycles without borrowing a native model session or fabricating an assignment.
            self.closure(db,{'readonly':False,'project':'','task':''},[{'kind':'source','sha256':sha256}])
            from bn_memory.source_policy_scope import invalidate
            invalidate(db,sha256)
        return {'sha256':sha256,'revision':revision+1,'policy':policy,'reason':reason,'classification':'operator_asserted_not_semantic_proof'}

    def record(self,db,binding,metadata, *, track=False):
        self.closure(db,binding,metadata.get('source_dependencies',[]),track=track)

    def visible(self,db,binding,raw):
        try:self.record(db,binding,json.loads(raw));return 1
        except (PermissionError,ValueError,RuntimeError):return 0
