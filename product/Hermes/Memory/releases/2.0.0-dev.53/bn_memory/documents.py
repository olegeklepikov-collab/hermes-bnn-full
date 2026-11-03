"""One corpus/coverage ledger in primary memory; extraction is not model understanding."""
import hashlib,json,os,shutil,sqlite3,subprocess,time,uuid
from pathlib import Path
from bn_memory.store import canonical,sha,SENSITIVE
from bn_memory.document_worker import FORMAT_REVISIONS

FORMATS={'.txt':'text','.md':'text','.ipynb':'json','.json':'json','.jsonl':'json','.ndjson':'json','.xml':'xml','.html':'html','.htm':'html','.sql':'sql',
 '.pptx':'pptx','.odt':'odt','.odp':'odp','.epub':'epub','.pdf':'pdf','.csv':'csv','.tsv':'tsv','.xlsx':'xlsx','.xlsm':'xlsx','.xls':'xls','.docx':'docx','.ods':'ods','.sqlite':'sqlite','.sqlite3':'sqlite','.db':'sqlite','.parquet':'parquet','.rtf':'rtf'}
PHASES={'read','plan','collect','analyse','verify','report','G','S','D'}

def current_decoder(row):
 meta=row.get('metadata') or json.loads(row['body'])
 return meta.get('decoder_revision',1)==FORMAT_REVISIONS.get(row['format'],1)

def filehash(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

class Documents:
 def __init__(self,broker):
  self.broker=broker;self.store=broker.store;self.root=Path(broker.config['state_root'])/'documents'
  self.root.mkdir(exist_ok=True,mode=0o700)
  with self.store.db() as c:
   c.execute('CREATE TABLE IF NOT EXISTS document_corpora(id TEXT PRIMARY KEY,scope TEXT,root TEXT,fingerprint TEXT,phases TEXT,status TEXT)')
   c.execute('CREATE TABLE IF NOT EXISTS document_sources(id TEXT PRIMARY KEY,corpus TEXT,path TEXT,sha256 TEXT,format TEXT,status TEXT,body TEXT)')
   c.execute('CREATE TABLE IF NOT EXISTS document_units(doc TEXT,unit INTEGER,body TEXT,PRIMARY KEY(doc,unit))')
   c.execute('CREATE TABLE IF NOT EXISTS document_pending(token TEXT PRIMARY KEY,sid TEXT,corpus TEXT,doc TEXT,unit INTEGER,begin INTEGER,end INTEGER,total INTEGER,phase TEXT,context TEXT,image TEXT,image_hash TEXT,state TEXT,api_id TEXT,profile_id TEXT NOT NULL)')
   if 'profile_id' not in {row[1] for row in c.execute('PRAGMA table_info(document_pending)')}:raise RuntimeError('explicit_document_namespace_migration_required')
   c.execute('CREATE TABLE IF NOT EXISTS document_partitions(id TEXT PRIMARY KEY,parent TEXT NOT NULL,members TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS document_deliveries(token TEXT,api_id TEXT,phase TEXT,received REAL,PRIMARY KEY(token,api_id,phase))')
   c.execute('CREATE INDEX IF NOT EXISTS document_pending_coverage ON document_pending(doc,unit,phase,"begin","end")')

 def authority_current(self,row):
  meta=row.get('metadata') or json.loads(row['body'])
  from bn_memory.path_relocation import operating_path
  given=operating_path(self.broker.config,meta.get('snapshot',''))
  roots=self.broker.config.get('document_authority_roots',[str(self.root)])
  if not given.is_absolute() or '..' in given.parts:return False
  for name in roots:
   root=Path(name).resolve()
   if given.is_relative_to(root):
    current=root
    for part in given.relative_to(root).parts:
     current=current/part
     if current.is_symlink():return False
    return True
  return False

 def corpus(self,sid,cid):
  scopes=self.store.scopes(self.store.binding(sid))
  with self.store.db() as c:r=c.execute('SELECT * FROM document_corpora WHERE id=?',(cid,)).fetchone()
  if not r or r['scope'] not in scopes:raise PermissionError('document_corpus_outside_scope')
  return dict(r)

 def catalogue(self,sid,args):
  from bn_memory.storage_guard import Storage,StorageUnavailable,fault
  storage=Storage(self.broker.config);storage.require('evidence')
  self.store.writable(sid)
  attachment=args['path'].startswith('attachment:')
  if attachment:
   relative=args['path'].removeprefix('attachment:');project=Path(self.broker.config['native_document_cache']);given=Path(relative)
   if '..' in given.parts:raise PermissionError('invalid_native_attachment')
   target=given if given.is_absolute() else project/given
   if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(project.resolve()):raise PermissionError('invalid_native_attachment')
   relative=str(target.relative_to(project))
   if any(q.is_symlink() for q in [target,*list(target.parents)[:len(Path(relative).parts)-1]]):raise PermissionError('invalid_native_attachment')
   authority=Path(self.broker.config['udr_host_state'])
   with sqlite3.connect(authority.as_uri()+'?mode=ro',uri=True) as db:
    registered=db.execute('SELECT 1 FROM attachments WHERE sid=? AND path=?',(sid,str(target))).fetchone()
   if not registered:raise PermissionError('attachment_not_registered_for_native_session')
  else:project,target=self.store.safe_file(sid,args['path'])
  phases=args.get('required_phases',['read'])
  if not isinstance(phases,list) or not phases or not set(phases)<=PHASES:raise ValueError('document_phases_invalid')
  scope=self.store.scope(sid,args.get('scope','project'));cid='CORP-'+sha(self.store.session_hash(sid)+':'+scope+':'+args['request_id'])[:24]
  fingerprint=sha(canonical({'path':str(target),'phases':phases,'scope':scope}))
  with self.store.db() as c:
   old=c.execute('SELECT * FROM document_corpora WHERE id=?',(cid,)).fetchone()
   if old and old['fingerprint']!=fingerprint:raise ValueError('document_catalogue_idempotency_conflict')
   if not old:c.execute('INSERT INTO document_corpora VALUES(?,?,?,?,?,?)',(cid,scope,str(target),fingerprint,canonical(phases),'indexing'))
  if old and old['status']=='inventoried':return self.status(sid,{'corpus_id':cid})
  # Every regular file is counted. No hidden format/exclusion is converted into success.
  enumeration_errors=[]
  if target.is_dir():
   paths=[]
   for base,dirs,files in os.walk(target,followlinks=False,onerror=enumeration_errors.append):
    paths.extend(Path(base)/name for name in dirs+files)
   paths.sort()
  else:paths=[target]
  for error in enumeration_errors:
   blocked_path=Path(error.filename);rel=str(blocked_path.relative_to(project));did='DOC-'+sha(cid+':'+rel)[:24]
   with self.store.db() as c:c.execute('INSERT OR IGNORE INTO document_sources VALUES(?,?,?,?,?,?,?)',(did,cid,rel,'','directory','blocked',canonical({'code':'directory_enumeration_failed','error_type':type(error).__name__})))
  for path in paths:
   if path.is_dir() and not path.is_symlink():continue
   rel=str(path.relative_to(project));did='DOC-'+sha(cid+':'+rel)[:24]
   with self.store.db() as c:exists=c.execute('SELECT 1 FROM document_sources WHERE id=?',(did,)).fetchone()
   if exists:continue
   status='registered';meta={'source_root':str(project),'source_path':str(path)};digest='';fmt=FORMATS.get(path.suffix.lower(),'unsupported')
   try:
    if not attachment:self.store.safe_file(sid,str(path))
    if path.is_symlink() or not path.is_file():raise PermissionError('unsupported_link_or_nonfile')
    directory=self.root/did;directory.mkdir(mode=0o700,exist_ok=True);snapshot=directory/('original'+path.suffix.lower())
    before=path.stat()
    storage.require('evidence',extra_bytes=before.st_size+1048576)
    if fmt=='sqlite':
     # No SQLite decoder runs in the host during acquisition. Preserve the exact file set.
     import zipfile
     parts=[path]+[Path(str(path)+suffix) for suffix in ['-wal'] if Path(str(path)+suffix).exists()]
     for part in parts:
      if part.is_symlink() or not part.is_file():raise PermissionError('sqlite_companion_must_be_regular')
     stamps={str(q):(q.stat().st_size,q.stat().st_mtime_ns,q.stat().st_ctime_ns) for q in parts};entries=[]
     with zipfile.ZipFile(snapshot,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as bundle:
      for part in parts:
       name='database.sqlite'+str(part)[len(str(path)):];bundle.write(part,name);entries.append({'name':name,'sha256':filehash(part),'bytes':part.stat().st_size})
      bundle.writestr('host-fileset.json',canonical({'contract':'BNRawSQLiteFileSetV1','parts':entries}))
     if any((q.stat().st_size,q.stat().st_mtime_ns,q.stat().st_ctime_ns)!=stamps[str(q)] for q in parts):raise ValueError('sqlite_source_changed_during_fileset_capture')
     meta.update(snapshot_method='exact_sqlite_fileset_bundle_no_parent_decoder',source_parts=entries)
    else:shutil.copyfile(path,snapshot);meta['snapshot_method']='exact_byte_copy'
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('source_changed_during_snapshot')
    digest=filehash(snapshot);snapshot.chmod(0o400)
    meta.update(snapshot=str(snapshot),source_bytes=before.st_size,snapshot_bytes=snapshot.stat().st_size,
      source_stat={'size':after.st_size,'mtime_ns':after.st_mtime_ns},model_received=False)
    if fmt=='unsupported':status='unsupported'
   except StorageUnavailable:raise
   except Exception as e:
    if fault(e):raise StorageUnavailable(fault(e),{'stage':'source_snapshot'}) from e
    status='blocked';meta={'code':type(e).__name__+':'+str(e)[:120]}
   with self.store.db() as c:c.execute('INSERT OR IGNORE INTO document_sources VALUES(?,?,?,?,?,?,?)',(did,cid,rel,digest,fmt,status,canonical(meta)))
  with self.store.db() as c:c.execute('UPDATE document_corpora SET status=? WHERE id=?',('incomplete_inventory' if enumeration_errors else 'inventoried',cid))
  return self.status(sid,{'corpus_id':cid})

 def partition(self,sid,args):
  self.store.writable(sid)
  parent=self.corpus(sid,args['corpus_id']);budget=args.get('max_characters',32768);offset=args.get('offset',0);limit=args.get('limit',20)
  if type(budget) is not int or not 1024<=budget<=262144 or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('document_partition_bounds_invalid')
  with self.store.db() as c:
   if c.execute('SELECT 1 FROM document_partitions WHERE id=?',(parent['id'],)).fetchone():raise PermissionError('recursive_document_partition_forbidden')
   units=[(r['doc'],r['unit'],json.loads(r['body'])['characters']) for r in c.execute('SELECT u.* FROM document_units u JOIN document_sources s ON s.id=u.doc WHERE s.corpus=? ORDER BY s.path,u.unit',(parent['id'],))]
  batches=[];current=[];used=0
  for did,index,size in units:
   if current and used+size>budget:batches.append(current);current=[];used=0
   current.append([did,index]);used+=size
  if current:batches.append(current)
  ids=[]
  with self.store.db() as c:
   for members in batches:
    fingerprint=sha(canonical({'parent':parent['id'],'members':members}));cid='PART-'+fingerprint[:24];ids.append(cid)
    c.execute('INSERT OR IGNORE INTO document_corpora VALUES(?,?,?,?,?,?)',(cid,parent['scope'],parent['root'],fingerprint,parent['phases'],'inventoried'))
    c.execute('INSERT OR IGNORE INTO document_partitions VALUES(?,?,?)',(cid,parent['id'],canonical(members)))
  status=self.status(sid,{'corpus_id':parent['id']})
  return {'corpus_id':parent['id'],'partitions_total':len(ids),'partitions':[{'corpus_id':cid,'members':batches[i]} for i,cid in list(enumerate(ids))[offset:offset+limit]],'next_offset':offset+limit if offset+limit<len(ids) else None,'has_more':offset+limit<len(ids),'missing_sources_count':status['missing_sources_count'],'unassigned_sources':status['missing_sources'],'reading_level':'plan_only','semantic_understanding_verified':False,'aggregation_required':'Keep each typed G/S/D product and provenance; compare cross-partition contradictions before global acceptance. Partition coverage contributes only original units actually delivered.'}

 def membership(self,sid,cid,did,index=None):
  self.corpus(sid,cid)
  row=self.source(sid,did)
  if row['corpus']==cid:return True
  with self.store.db() as c:r=c.execute('SELECT members FROM document_partitions WHERE id=?',(cid,)).fetchone()
  return bool(r and any(x[0]==did and (index is None or x[1]==index) for x in json.loads(r[0])))

 def source(self,sid,did):
  with self.store.db() as c:r=c.execute('SELECT * FROM document_sources WHERE id=?',(did,)).fetchone()
  if not r:raise KeyError('document_source_not_found')
  row=dict(r);self.corpus(sid,row['corpus'])
  if self.store.binding(sid)['readonly'] and self.broker.config.get('w3_enabled'):
   from bn_memory.assignment_resources import require
   granted=require(self.store,sid,'documents',did)
   if granted['sha256']!=row['sha256']:raise PermissionError('assigned_document_version_changed')
  if row['status'] in {'registered','extracting','extracted','parse_blocked'} and not self.authority_current(row):raise PermissionError('legacy_document_intake_rebind_required')
  from bn_memory.source_visibility import Visibility
  Visibility(self.store).source(sid,row['sha256'])
  row['metadata']=json.loads(row['body']);return row

 def extract(self,sid,args):
  from bn_memory.storage_guard import Storage
  storage=Storage(self.broker.config)
  self.store.writable(sid)
  row=self.source(sid,args['doc_id'])
  if row['status']=='extracted':
   if not current_decoder(row):raise ValueError('document_decoder_revision_stale:catalogue_a_new_request_id_from_the_same_original')
   return self.describe(sid,{'doc_id':row['id']})
  if row['status']=='parse_blocked' and not args.get('retry_after_repair',False):raise ValueError('parser_repair_required_before_retry')
  if row['status'] not in {'registered','extracting','parse_blocked'}:raise ValueError('document_not_extractable:'+row['status'])
  from bn_memory.path_relocation import operating_path
  directory=self.root/row['id'];snapshot=operating_path(self.broker.config,row['metadata']['snapshot'])
  if snapshot.is_symlink():raise ValueError('document_snapshot_integrity_failed')
  storage.require('evidence')
  from bn_memory.parser_host import run_step
  result=run_step({'path':str(snapshot),'format':row['format'],'output':str(directory/'parser-v3'),
      'xls_java':self.broker.config.get('xls_java'),'expected_sha256':row['sha256']},self.broker.config['document_python'],{**(self.broker.config.get('parser_limits') or {}),**({'reserve_free_bytes':max((self.broker.config.get('parser_limits') or {}).get('reserve_free_bytes',536870912),storage.policy['background_free_bytes'])} if storage.enabled else {})},path_config=self.broker.config)
  if result['status']=='busy':return result
  metadata={**row['metadata'],**result,'parse_output':result.get('output_directory',str(directory/'parser-v3/units'))}
  status='extracted' if result['status']=='extracted' else 'extracting' if result['status']=='partial' else 'parse_blocked'
  unit_index=Path(result.get('unit_index',directory/'parser-v3/units.jsonl'))
  indexed=row['metadata'].get('indexed_bytes',0)
  with self.store.db() as c:
   if unit_index.exists():
    with unit_index.open('rb') as f:
     f.seek(indexed)
     for line in f:
      unit=json.loads(line);c.execute('INSERT OR REPLACE INTO document_units VALUES(?,?,?)',(row['id'],unit['index'],canonical(unit)))
     metadata['indexed_bytes']=f.tell()
   c.execute('UPDATE document_sources SET status=?,body=? WHERE id=?',(status,canonical(metadata),row['id']))
  return self.describe(sid,{'doc_id':row['id']})

 def describe(self,sid,args):
  row=self.source(sid,args['doc_id']);start=args.get('offset',0);limit=args.get('limit',20)
  if type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('document_page_invalid')
  with self.store.db() as c:units=[json.loads(r[0]) for r in c.execute('SELECT body FROM document_units WHERE doc=? ORDER BY unit LIMIT ? OFFSET ?',(row['id'],limit+1,start))]
  return {k:row[k] for k in ['id','corpus','path','sha256','format','status']}|{'metadata':row['metadata'],'decoder_current':current_decoder(row),'units':units[:limit],'has_more':len(units)>limit,'next_offset':start+limit if len(units)>limit else None,'reading_level':'metadata_and_unit_index_only'}

 def read(self,sid,args):
  row=self.source(sid,args['doc_id']);index=args['unit'];phase=args.get('phase','read')
  if not self.membership(sid,args['corpus_id'],row['id'],index):raise PermissionError('document_not_in_assigned_corpus')
  if phase not in PHASES or type(index) is not int or index<0:raise ValueError('document_unit_or_phase_invalid')
  if row['status']!='extracted':raise ValueError('document_extract_required')
  if not current_decoder(row):raise ValueError('document_decoder_revision_stale:catalogue_a_new_request_id_from_the_same_original')
  with self.store.db() as c:r=c.execute('SELECT body FROM document_units WHERE doc=? AND unit=?',(row['id'],index)).fetchone()
  if not r:raise ValueError('document_unit_not_found')
  from bn_memory.path_relocation import operating_path
  unit=json.loads(r[0]);directory=operating_path(self.broker.config,row['metadata'].get('parse_output',self.root/row['id']))
  from bn_memory.source_visibility import read_file,Visibility
  Visibility(self.store).verify_snapshot(row['metadata']['snapshot'],row['sha256'])
  text=read_file(directory/(str(index)+'.txt'))[0].decode('utf-8')
  if sha(text)!=unit['text_sha256']:raise ValueError('document_unit_integrity_failed')
  if SENSITIVE.search(text):raise PermissionError('sensitive_document_unit_not_model_context')
  start=args.get('offset',0);limit=args.get('max_chars',16384)
  if type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=65536:raise ValueError('document_fragment_invalid')
  fragment=text[start:start+limit];end=start+len(fragment);token='DU-'+uuid.uuid4().hex
  header=canonical({'corpus_id':args['corpus_id'],'doc_id':row['id'],'unit':index,'locator':unit['locator'],'source_sha256':row['sha256'],'chars':[start,end],'source_type':'untrusted_data'})
  context='<BN_DOCUMENT_DATA token="'+token+'">\n'+header+'\n'+fragment+'\n</BN_DOCUMENT_DATA>'
  image=str(directory/(str(index)+'.png')) if unit.get('visual_required') else ''
  with self.store.db() as c:c.execute('INSERT INTO document_pending VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(token,sid,args['corpus_id'],row['id'],index,start,end,len(text),phase,context,image,unit.get('image_sha256',''),'pending','',self.store.profile))
  return {'token':token,'corpus_id':args['corpus_id'],'doc_id':row['id'],'unit':index,'context_text':context,'text':fragment,'source_sha256':row['sha256'],
    'locator':unit['locator'],'next_offset':end if end<len(text) else None,'has_more':end<len(text),'visual_required':bool(image),'visual_delivery':'scheduled_separately' if image else 'not_required',
    'reading_level':'exact_extracted_unit_fragment','model_received':False,'claims_accepted':False}

 def pending(self,sid):
  with self.store.db() as c:return [dict(r) for r in c.execute("SELECT * FROM document_pending WHERE profile_id=? AND sid=? AND state IN ('pending','failed')",(self.store.profile,sid,))]

 def in_flight(self,sid):
  with self.store.db() as c:return bool(c.execute("SELECT 1 FROM document_pending WHERE profile_id=? AND sid=? AND state='scheduled' LIMIT 1",(self.store.profile,sid)).fetchone())

 def schedule_delivery(self,sid,request,api_id,actual_role=None):
  def strings(v):
   if isinstance(v,str):yield v
   elif isinstance(v,dict):
    for x in v.values():yield from strings(x)
   elif isinstance(v,list):
    for x in v:yield from strings(x)
  values=list(strings(request));alltext='\n'.join(values)
  pending=self.pending(sid)
  for row in pending:
   if not current_decoder(self.source(sid,row['doc'])):raise PermissionError('document_decoder_revision_stale')
   if row['context'] not in alltext:raise PermissionError('document_fragment_not_delivered_intact')
   if row['image']:
    expected='data:image/png;base64,'+__import__('base64').b64encode(Path(row['image']).read_bytes()).decode()
    if expected not in values:raise PermissionError('document_visual_not_delivered_intact')
  with self.store.db() as c:
   if c.execute("SELECT 1 FROM document_pending WHERE profile_id=? AND sid=? AND state='scheduled' LIMIT 1",(self.store.profile,sid)).fetchone():raise PermissionError('document_delivery_already_in_flight')
   for row in pending:
    phase=actual_role or row['phase']
    if actual_role is None and phase in {'G','S','D'}:phase='read' # A parent cannot fake a G/S/D receipt.
    changed=c.execute("UPDATE document_pending SET state='scheduled',api_id=?,phase=? WHERE profile_id=? AND token=? AND state IN ('pending','failed')",(api_id,phase,self.store.profile,row['token'])).rowcount
    if changed!=1:raise PermissionError('document_delivery_claim_changed')

 def confirm_response(self,sid,api_id,error=None):
  with self.store.db() as c:
   rows=c.execute("SELECT token,phase FROM document_pending WHERE profile_id=? AND sid=? AND api_id=? AND state='scheduled'",(self.store.profile,sid,api_id)).fetchall()
   if not error:
    for r in rows:c.execute('INSERT OR IGNORE INTO document_deliveries VALUES(?,?,?,?)',(r['token'],api_id,r['phase'],time.time()))
   c.execute('UPDATE document_pending SET state=? WHERE profile_id=? AND sid=? AND api_id=? AND state=\'scheduled\'',('failed' if error else 'received',self.store.profile,sid,api_id))

 def status(self,sid,args):
  child=self.store.binding(sid)['readonly'];selected=None
  if child:
   if not self.broker.config.get('w3_enabled'):raise PermissionError('child_corpus_aggregate_not_qualified')
   from bn_memory.assignment_resources import read
   selected=read(self.store,self.store.binding(sid))['documents']
  cid=args['corpus_id'];corpus=self.corpus(sid,cid);phases=args.get('_phases',json.loads(corpus['phases']))
  if not phases or not set(phases)<=PHASES:raise ValueError('document_phases_invalid')
  with self.store.db() as c:
   partition=c.execute('SELECT * FROM document_partitions WHERE id=?',(cid,)).fetchone();original=partition['parent'] if partition else cid;members={tuple(x) for x in json.loads(partition['members'])} if partition else None
   sources=[dict(r) for r in c.execute('SELECT id,path,sha256,format,status,body FROM document_sources WHERE corpus=? ORDER BY path',(original,))]
   if args.get('_doc_ids') is not None:sources=[r for r in sources if r['id'] in args['_doc_ids']]
   if selected is not None:
    sources=[r for r in sources if r['id'] in selected]
    if not sources:raise PermissionError('corpus_not_assigned_to_native_child')
   if members is not None:sources=[r for r in sources if any(x[0]==r['id'] for x in members)]
   stale={r['id'] for r in sources if r['status']=='extracted' and not current_decoder(r)}
   unbound={r['id'] for r in sources if r['status']=='extracted' and not self.authority_current(r)}
   stale.update(unbound)
   missing=[{'id':r['id'],'path':r['path'],'status':'decoder_revision_stale' if r['id'] in stale else r['status']} for r in sources if r['status']!='extracted' or r['id'] in stale]
   phase_status={}
   for phase in phases:
    query='SELECT u.doc,u.unit,u.body,p."begin",p."end" FROM document_units u JOIN document_sources s ON s.id=u.doc\nLEFT JOIN document_pending p ON p.doc=u.doc AND p.unit=u.unit AND p.phase=? AND p.profile_id=?\nAND EXISTS(SELECT 1 FROM document_deliveries d WHERE d.token=p.token AND d.phase=p.phase)\nAND (? IS NULL OR p.sid=?) WHERE s.corpus=? ORDER BY u.doc,u.unit,p."begin",p."end"'
    current=None;meta=None;end=0;received=False;gap=False;seen=0;complete=0;gaps=[]
    def outcome(key,meta,end,received,gap):
     ok=received and not gap and end>=meta['characters'] and not meta.get('unhandled_visuals') and key[0] not in stale
     if not ok and len(gaps)<20:gaps.append({'doc_id':key[0],'unit':key[1],'covered_characters':end,'required':meta['characters'],'unhandled_visuals':meta.get('unhandled_visuals',False),'decoder_current':key[0] not in stale})
     return int(ok)
    recipient=args.get('_recipient_sid')
    for row in c.execute(query,(phase,self.store.profile,recipient,recipient,original)):
     key=(row[0],row[1])
     if args.get('_doc_ids') is not None and row[0] not in args['_doc_ids']:continue
     if selected is not None and row[0] not in selected:continue
     if members is not None and key not in members:continue
     if key!=current:
      if current is not None:complete+=outcome(current,meta,end,received,gap)
      current=key;meta=json.loads(row[2]);end=0;received=False;gap=False;seen+=1
     if row[3] is not None:
      received=True
      if row[3]>end:gap=True
      if not gap:end=max(end,row[4])
    if current is not None:complete+=outcome(current,meta,end,received,gap)
    phase_status[phase]={'units_received_completely':complete,'units_expected':seen,'complete':bool(sources) and bool(seen) and not missing and complete==seen,'gap_examples':gaps}
  start=args.get('offset',0);limit=args.get('limit',20)
  if type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('document_page_invalid')
  view=[{k:r[k] for k in ['id','path','sha256','format','status']} for r in sources[start:start+limit]]
  return {'corpus_id':cid,'inventory_complete':corpus['status']=='inventoried','files_total':sum(r['format']!='directory' for r in sources),'entries_total':len(sources),'blocked_directories_count':sum(r['format']=='directory' for r in sources),'files_extracted':sum(r['status']=='extracted' and r['id'] not in stale for r in sources),'stale_decoder_sources_count':len(stale),
    'missing_sources_count':len(missing),'missing_sources':missing[:20],'sources':view,'has_more':start+limit<len(sources),'next_offset':start+limit if start+limit<len(sources) else None,
    'phases':phase_status,'model_delivery_complete':all(v['complete'] for v in phase_status.values()),'semantic_understanding_verified':False,'scientific_acceptance':False}
