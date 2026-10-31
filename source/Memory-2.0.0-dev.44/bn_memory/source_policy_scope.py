"""Source-use witnesses and scoped retrieval identity. No grant or model-side policy edit."""
import hashlib,json
from bn_memory import record_metadata

FIELDS=('profile_id','sid','project','task','parent','readonly','role','purpose','assignment_id')
def canonical(v):return record_metadata.canonical(v)
def hash_value(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def key(binding):return hash_value({k:binding.get(k) for k in FIELDS})

def install(db):
    db.execute('''CREATE TABLE source_uses(
        profile_id TEXT NOT NULL,sid TEXT NOT NULL,binding_hash TEXT NOT NULL,
        sha256 TEXT NOT NULL,revision INTEGER NOT NULL,policy_hash TEXT NOT NULL,
        PRIMARY KEY(profile_id,sid,binding_hash,sha256),
        FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid))''')
    db.execute('CREATE INDEX source_uses_by_source ON source_uses(sha256)')
    db.execute("INSERT INTO meta VALUES('source_admission_scope_contract','1')")

def require(db):
    row=db.execute("SELECT value FROM meta WHERE key='source_admission_scope_contract'").fetchone()
    if not row or row[0]!='1':raise RuntimeError('explicit_source_scope_migration_required')

def remember(db,binding,sha256,revision,policy):
    if 'sid' not in binding:return
    require(db);identity=(binding['profile_id'],binding['sid'],key(binding),sha256)
    captured=hash_value(policy)
    db.execute('INSERT OR IGNORE INTO source_uses VALUES(?,?,?,?,?,?)',(*identity,revision,captured))
    row=db.execute('SELECT revision,policy_hash FROM source_uses WHERE profile_id=? AND sid=? AND binding_hash=? AND sha256=?',identity).fetchone()
    if tuple(row)!=(revision,captured):raise PermissionError('used_source_policy_changed_requires_new_turn')

def check(store,db,binding):
    from bn_memory.source_visibility import Visibility
    require(db);v=Visibility(store)
    for row in db.execute('SELECT sha256,revision,policy_hash FROM source_uses WHERE profile_id=? AND sid=? AND binding_hash=?',
                          (store.profile,binding['sid'],key(binding))).fetchall():
        policy,revision=v.policy(db,row['sha256'])
        if revision!=row['revision'] or hash_value(policy)!=row['policy_hash']:
            raise PermissionError('used_source_policy_changed_requires_new_turn')

def begin(store,db,binding):
    """Only a new native preparation may refresh use witnesses, after role checks."""
    from bn_memory.source_visibility import Visibility
    require(db);v=Visibility(store);identity=(store.profile,binding['sid'],key(binding))
    roots={r[0] for r in db.execute('SELECT sha256 FROM source_uses WHERE profile_id=? AND sid=? AND binding_hash=?',identity)}
    roots.update(binding.get('_assigned_sources',[]))
    # Update together in the caller transaction; a denied closure rolls all back.
    for sha256 in roots:
        policy,revision=v.policy(db,sha256)
        db.execute('UPDATE source_uses SET revision=?,policy_hash=? WHERE profile_id=? AND sid=? AND binding_hash=? AND sha256=?',
                   (revision,hash_value(policy),*identity,sha256))
    for sha256 in sorted(roots):
        if binding['readonly']:v.closure(db,binding,[{'kind':'source','sha256':sha256}],track=True)
        else:
            policy,revision=v.policy(db,sha256);remember(db,binding,sha256,revision,policy)

def invalidate(db,sha256):
    """Invalidate current consumers, including transitive sources seen by closure."""
    require(db)
    rows=db.execute('''SELECT s.*,u.binding_hash AS used_binding FROM source_uses u
        JOIN sessions s ON s.profile_id=u.profile_id AND s.sid=u.sid WHERE u.sha256=?''',(sha256,)).fetchall()
    affected=set()
    for row in rows:
        binding=dict(row)
        if key(binding)==row['used_binding']:affected.add((row['profile_id'],row['sid']))
    for identity in sorted(affected):
        db.execute('UPDATE sessions SET context=NULL,turn=NULL WHERE profile_id=? AND sid=?',identity)
        db.execute("UPDATE context_admissions SET status='failed' WHERE profile_id=? AND sid=? AND status IN ('preparing','ready')",identity)
    return len(affected)

def retrieval_fingerprint(store,db,binding):
    """Policies capable of affecting this scoped selection, not every owner policy."""
    from bn_memory.source_visibility import Visibility,dependencies
    require(db);v=Visibility(store);roots=[]
    own=db.execute('SELECT sha256 FROM source_uses WHERE profile_id=? AND sid=? AND binding_hash=?',
                   (store.profile,binding['sid'],key(binding))).fetchall()
    roots.extend({'kind':'source','sha256':r[0]} for r in own)
    roots.extend({'kind':'source','sha256':s} for s in binding.get('_assigned_sources',[]))
    role_sql,args=record_metadata.search_filter(binding)
    rows=db.execute('''SELECT r.id,r.revision FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision
        JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision
        WHERE r.status='recorded' AND r.scope IN (?,?,?)'''+role_sql,store.scopes(binding)+args).fetchall()
    for row in rows:roots.extend(dependencies(record_metadata.read(db,row['id'],row['revision']).get('source_dependencies',[])))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_sources'").fetchone():
        rows=db.execute('''SELECT DISTINCT s.sha256 FROM document_sources s JOIN document_corpora c ON s.corpus=c.id
                            WHERE c.scope IN (?,?,?)''',store.scopes(binding)).fetchall()
        assigned=set(binding.get('_assigned_sources',[]))
        roots.extend({'kind':'source','sha256':r[0]} for r in rows if not binding['readonly'] or r[0] in assigned)
    stack=[(item,()) for item in roots];seen={};nodes=[]
    while stack:
        item,ancestors=stack.pop();identity=canonical(item)
        if identity in ancestors:raise PermissionError('cyclic_source_dependencies')
        if identity in seen:continue
        if len(ancestors)>=256:raise PermissionError('split_dependency_closure_required')
        seen[identity]=True
        if item['kind']=='source':
            policy,revision=v.policy(db,item['sha256']);nodes.append([item,revision,hash_value(policy)])
        else:
            row=db.execute('SELECT r.* FROM records r JOIN current u ON r.id=u.id AND r.revision=u.revision WHERE r.id=?',(item['id'],)).fetchone()
            if row is None:nodes.append([item,'missing']);continue
            policy=record_metadata.read(db,row['id'],row['revision'])
            nodes.append([item,row['revision'],row['content_hash'],row['status'],hash_value(policy)])
        stack.extend((child,(*ancestors,identity)) for child in dependencies(policy.get('source_dependencies',[])))
    return hash_value(sorted(nodes,key=lambda n:canonical(n[0])))

def migrate(db):
    old=db.execute("SELECT value FROM meta WHERE key='source_admission_scope_contract'").fetchone()
    if old:
        require(db);return {'already_applied':True}
    db.execute('BEGIN IMMEDIATE');install(db)
    # One explicit cutover retires old receipts. Ordinary source edits never do this.
    db.execute("UPDATE context_admissions SET status='failed' WHERE status IN ('ready','preparing')")
    db.execute('UPDATE sessions SET context=NULL,turn=NULL')
    return {'applied':True,'legacy_receipts_retired_once':True,'records_or_policies_changed':False}

def invalidate_record(db,rid):
    """Withdraw one record without clearing independent projects or profiles.

    Follow only declared current record/source dependencies. Missing semantic
    dependencies are not invented; historical versions remain unchanged.
    """
    from bn_memory.source_visibility import dependencies
    require(db);reverse={};scopes={}
    def node(item):return (item['kind'],item['id'] if item['kind']=='record' else item['sha256'])
    records=db.execute('''SELECT r.id,r.scope,m.attributes FROM records r
        JOIN current u ON u.id=r.id AND u.revision=r.revision
        JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision''').fetchall()
    for row in records:
        target=('record',row['id']);scopes[target]=row['scope']
        for dep in dependencies(json.loads(row['attributes']).get('source_dependencies',[])):reverse.setdefault(node(dep),set()).add(target)
    policies=db.execute('''SELECT p.sha256,p.policy FROM source_policies p JOIN
        (SELECT sha256,MAX(revision) AS revision FROM source_policies GROUP BY sha256) q
        ON q.sha256=p.sha256 AND q.revision=p.revision''').fetchall()
    for row in policies:
        for dep in dependencies(json.loads(row['policy']).get('source_dependencies',[])):reverse.setdefault(node(dep),set()).add(('source',row['sha256']))
    pending=[('record',rid)];affected=set()
    while pending:
        item=pending.pop()
        if item in affected:continue
        affected.add(item);pending.extend(reverse.get(item,()))
    affected_scopes={scopes[n] for n in affected if n in scopes};count=0
    for row in db.execute('SELECT profile_id,sid,project,task FROM sessions').fetchall():
        if not affected_scopes.intersection({'owner','project:'+row['project'],'task:'+row['task']}):continue
        identity=(row['profile_id'],row['sid']);count+=1
        db.execute('UPDATE sessions SET context=NULL,turn=NULL WHERE profile_id=? AND sid=?',identity)
        db.execute("UPDATE context_admissions SET status='failed' WHERE profile_id=? AND sid=? AND status IN ('preparing','ready')",identity)
    for kind,identifier in affected:
        if kind=='source':count+=invalidate(db,identifier)
    return count
