"""Owned service output -> project bytes -> existing isolated document intake."""
from pathlib import Path
import base64,hashlib,json,re,os,subprocess,uuid
from bn_memory.store import canonical,sha
def dispatch(broker,sid,args):
 from bn_memory.write_origin import for_binding
 binding=broker.store.binding(sid)
 if binding['readonly'] or not for_binding(binding).get('attempt_id'):raise PermissionError('parent_native_service_file_authority_required')
 broker.store.writable(sid)
 if args['action']=='snapshot':
  _,source=broker.store.safe_file(sid,args['path'])
  if not source.is_file() or source.is_symlink():raise PermissionError('one_owned_regular_file_required')
  if any(Path(str(source)+suffix).exists() and Path(str(source)+suffix).stat().st_size for suffix in ['-wal','-journal']):raise ValueError('active_database_requires_a_consistent_native_database_export_not_raw_file_copy')
  project=Path(broker.config['projects'][binding['project']]).resolve();pending=project/'.service-inbox'/('.pending-'+uuid.uuid4().hex);pending.mkdir(parents=True,mode=0o700)
  target=pending/source.name;before=source.stat()
  result=subprocess.run(['/bin/cp','-c',str(source),str(target)],capture_output=True)
  if result.returncode:
   import shutil
   if target.exists():target.unlink() # Only this operation's newly-created temporary copy.
   with source.open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst,length=1024*1024)
  digest=hashlib.sha256();guard=__import__('bn_memory.artifacts',fromlist=['Artifacts']).Artifacts(broker);secrets=guard.secrets();carry=b''
  with target.open('rb') as f:
   while chunk:=f.read(1024*1024):
    digest.update(chunk);guard.sensitive(carry+chunk,secrets);carry=(carry+chunk)[-max([16384]+[len(x) for x in secrets]):]
  after=source.stat()
  if (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise PermissionError('service_snapshot_original_changed')
  value=digest.hexdigest();dest=project/'.service-inbox'/value/source.name;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  if dest.exists():
   with dest.open('rb') as f:existing=hashlib.file_digest(f,'sha256').hexdigest()
   if existing!=value:raise PermissionError('content_addressed_snapshot_not_overwritten')
   target.unlink();pending.rmdir()
  else:target.rename(dest);pending.rmdir()
  dest.chmod(0o400)
  provenance={'kind':'native_project_input_snapshot','original_path':str(source),'bytes_preserved':True}
  with broker.store.db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS service_materializations(profile_id TEXT,sid TEXT,path TEXT,sha256 TEXT,provenance TEXT,PRIMARY KEY(profile_id,path))')
   db.execute('INSERT OR IGNORE INTO service_materializations VALUES(?,?,?,?,?)',(broker.store.profile,sid,str(dest),value,canonical(provenance)))
  return {'path':str(dest),'sha256':value,'bytes':after.st_size,'original_path':str(source),'reading_level':'immutable_bytes_snapshot_not_semantic_read','model_read':False}
 if args['action']=='intake':
  _,path=broker.store.safe_file(sid,args['path'])
  from bn_memory.documents import Documents
  docs=Documents(broker);inventory=docs.catalogue(sid,{'path':str(path),'request_id':args['request_id'],'scope':'project','required_phases':args.get('required_phases',['read'])})
  if inventory['files_total']!=1 or len(inventory['sources'])!=1:raise ValueError('one_original_per_service_intake_required')
  did=inventory['sources'][0]['id'];extracted=docs.extract(sid,{'doc_id':did})
  return {'status':'native_document_intake','corpus_id':inventory['corpus_id'],'doc_id':did,'parser':extracted,'reading_level':'intake_and_extraction_not_model_read','model_read':False,'scientific_acceptance':False,'next':'Continue document_extract if partial; then document_describe/document_read every requested unit and next_offset; document_status confirms actual received coverage.'}
 rid=args['result_id']
 with broker.store.db() as db:
  row=db.execute("SELECT * FROM service_results WHERE profile_id=? AND result_id=? AND state='returned'",(broker.store.profile,rid)).fetchone()
 if row is None:raise ValueError('preserved_service_result_required')
 owner=broker.store.binding(row['sid']);allowed={row['sid']}
 while owner.get('parent'):
  allowed.add(owner['parent']);owner=broker.store.binding(owner['parent'])
 if sid not in allowed:raise PermissionError('service_output_belongs_to_another_work')
 value=json.loads(row['body']);provenance={'service_result_id':rid,'service_response_sha256':sha(row['body'])}
 if 'content_index' in args:
  index=args['content_index'];content=value.get('content',[])
  if type(index) is not int or not 0<=index<len(content) or content[index].get('type')!='image':raise ValueError('recorded_image_block_required')
  item=content[index]
  if item.get('mimeType') not in {'image/png','image/jpeg','image/webp'}:raise PermissionError('nonexecutable_bitmap_required')
  data=base64.b64decode(item['data'],validate=True);provenance['content_index']=index
 else:
  receipts=value.get('_bnn_file_receipts',[]);selected=next((x for x in receipts if x['path']==args.get('source_file')),None)
  if selected is None:raise PermissionError('original_host_captured_file_receipt_required')
  from bn_memory.path_relocation import operating_path
  path=operating_path(broker.config,selected['path'])
  if path.is_symlink() or not path.is_file():raise PermissionError('owned_regular_output_required')
  data=path.read_bytes()
  if hashlib.sha256(data).hexdigest()!=selected['sha256']:raise PermissionError('service_output_changed_since_delivery')
  provenance.update(source_path=selected['path'],source_file_sha256=selected['sha256'])
 from bn_memory.artifacts import Artifacts
 guard=Artifacts(broker);guard.sensitive(data,guard.secrets())
 name=args['file_name']
 if name!=Path(name).name or not name or name in {'.','..'} or '/' in name or '\\' in name:raise ValueError('one_safe_output_basename_required')
 digest=hashlib.sha256(data).hexdigest();root=Path(broker.config['projects'][binding['project']]).resolve();target=root/'.service-inbox'/digest/name
 target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if target.exists():
  if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise PermissionError('existing_project_output_not_overwritten')
 else:
  with target.open('xb') as f:f.write(data)
  target.chmod(0o600)
 with broker.store.db() as db:
  db.execute('CREATE TABLE IF NOT EXISTS service_materializations(profile_id TEXT,sid TEXT,path TEXT,sha256 TEXT,provenance TEXT,PRIMARY KEY(profile_id,path))')
  db.execute('INSERT OR IGNORE INTO service_materializations VALUES(?,?,?,?,?)',(broker.store.profile,sid,str(target),digest,canonical(provenance)))
 return {'status':'materialized_owned_project_file','path':str(target),'bytes':len(data),'sha256':digest,'provenance':provenance,'reading_level':'exact_original_bytes_not_document_read','next':'Use service_file intake for documents; memory_artifact register/send for delivery, under its own required control.'}

def r_inputs(broker,sid,entry,paths):
 binding=broker.store.binding(sid);project=Path(broker.config['projects'][binding['project']]).resolve();selected=[]
 for name in paths:
  _,path=broker.store.safe_file(sid,name)
  if not path.resolve().is_relative_to(project/'.service-inbox'):raise PermissionError('R_input_requires_service_file_snapshot_or_materialize')
  if binding['readonly']:
   from bn_memory.assignment_resources import file
   file(broker.store,sid,path)
  with broker.store.db() as db:
   row=db.execute('SELECT sha256 FROM service_materializations WHERE profile_id=? AND path=?',(broker.store.profile,str(path))).fetchone()
   if row is None:
    from bn_memory.path_relocation import operating_path
    for previous,digest in db.execute('SELECT path,sha256 FROM service_materializations WHERE profile_id=? AND sha256=?',(broker.store.profile,path.parent.name)):
     if operating_path(broker.config,previous)==path:row=(digest,);break
  if row is None:raise PermissionError('host_captured_R_input_provenance_required')
  with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
  if digest!=row[0]:raise PermissionError('R_input_snapshot_changed')
  from bn_memory.source_visibility import Visibility
  from bn_memory.record_metadata import enforce
  with broker.store.db() as db:policy,_=Visibility(broker.store).policy(db,digest);enforce(binding,policy)
  selected.append({'path':str(path),'requested_path':name,'sha256':digest})
 entry['_input_snapshots']=selected;entry['_input_read_root']=str(project/'.service-inbox') if not binding['readonly'] else None
 if binding['readonly']:
  from bn_memory.assignment_resources import read
  all_files=read(broker.store,binding)['files']
  entry['_input_allowed_files']=[p for p in all_files if Path(p).is_relative_to(project/'.service-inbox')]
 return selected
