"""Deterministic parser host. OS restrictions apply before untrusted bytes are opened."""
from pathlib import Path
import fcntl,hashlib,json,os,platform,signal,subprocess,sys,tempfile,time,uuid
from contextvars import ContextVar
CANCEL_EVENT=ContextVar('bn_parser_cancel',default=None)
VERSION='bn-parser/1.0.0'
def filehash(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  while b:=f.read(4*1024*1024):h.update(b)
 return h.hexdigest()
def prefixhash(path,limit):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  while limit:
   b=f.read(min(limit,4*1024*1024))
   if not b:raise ValueError('parser_index_truncated')
   h.update(b);limit-=len(b)
 return h.hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def atomic(p,v):
 t=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp');t.write_text(canonical(v));t.chmod(0o600);os.replace(t,p)
def expression(kind,path):return '('+kind+' '+json.dumps(str(Path(path).resolve()),ensure_ascii=False)+')'
def profile(reads,writes,execs,compute=False,java=False):
 read=[expression('literal',p) for p in ['/','/dev','/dev/null','/dev/random','/dev/urandom','/dev/zero','/dev/dtracehelper']]+[expression('subpath',p) for p in ['/System','/usr','/bin','/sbin','/private/var/db/dyld','/private/var/db/timezone','/Library/Fonts','/Library/Apple','/Library/AssetsV2','/opt/homebrew/Cellar','/opt/homebrew/opt']]
 for p in reads+writes:
  p=Path(p).resolve();read.append(expression('subpath' if p.is_dir() else 'literal',p))
  read.extend(expression('literal',q) for q in p.parents)
 write=[expression('subpath',p) for p in writes]+[expression('literal','/dev/null'),expression('literal','/dev/dtracehelper')]
 exe=[expression('literal',p) for p in execs]
 deny=lambda op,allow:'(deny '+op+' (require-all '+' '.join('(require-not '+x+')' for x in allow)+'))'
 extra=''
 if compute:
  names=['com.apple.system.opendirectoryd.membership','com.apple.system.opendirectoryd.libinfo','com.apple.bsd.dirhelper','com.apple.MTLCompilerService','com.apple.appleneuralengine','com.apple.cvmsServ']
  extra='(allow mach-lookup '+''.join('(global-name '+json.dumps(n)+')' for n in names)+')(allow mach-lookup (global-name-regex "^com[.]apple[.]MTLCompilerService"))(allow iokit-open '+''.join('(iokit-user-client-class '+json.dumps(n)+')' for n in ['AGXDeviceUserClient','IOSurfaceRootUserClient','IOSurfaceAcceleratorClient','H1xANELoadBalancerDirectPathClient'])+')(allow sysctl-read (sysctl-name "kern.hv_vmm_present"))'
 if java:extra+='(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo") (global-name "com.apple.system.opendirectoryd.membership"))(allow file-read-data (literal "/private/etc/passwd"))(allow signal (target self))'
 return '(version 1)(deny default)'+extra+'(allow file-read-metadata)(allow sysctl-read (sysctl-name-regex "^(hw[.].*|machdep[.]cpu[.].*|kern[.](os.*|hostname|argmax|version|boottime|maxfiles.*|maxproc.*)|sysctl[.].*)$"))(allow process-fork)'+'(allow file-read-data (require-any '+' '.join(read)+'))'+'(allow file-write* (require-any '+' '.join(write)+'))'+'(allow process-exec (require-any '+' '.join(exe)+'))'
def runtime(python):
 r=subprocess.run([python,'-I','-B','-c','import sys,json;print(json.dumps([sys.prefix,sys.base_prefix]))'],capture_output=True,text=True,check=True,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'})
 return json.loads(r.stdout)
def run_step(req,python,limits=None):
 lockfile=Path(__file__).resolve().parents[1]/'parser-runtime.json'
 if not lockfile.is_file():raise RuntimeError('parser_runtime_not_admitted')
 pin=json.loads(lockfile.read_text())
 if str(Path(python).absolute())!=pin['python'] or filehash(Path(python).resolve())!=pin['python_binary_hash']:raise RuntimeError('parser_runtime_integrity_failed')
 ocr=Path(__file__).resolve().parents[1]/'vision-ocr'
 if filehash(ocr)!=pin['ocr_binary_hash']:raise RuntimeError('parser_ocr_integrity_failed')
 if platform.system()!='Darwin' or platform.machine()!='arm64' or not Path('/usr/bin/sandbox-exec').is_file():raise RuntimeError('required_parser_os_isolation_unavailable')
 limits={'step_seconds':45,'max_units':64,'max_processes':16,'reserve_free_bytes':536870912,'max_rss_bytes':1536*1024*1024,'max_file_bytes':128*1024*1024,**(limits or {})}
 if any(type(v) is not int or v<=0 for v in limits.values()):raise ValueError('invalid_parser_limits')
 source=Path(req['path']);output=Path(req['output']);worker=Path(__file__).with_name('document_worker.py')
 if source.is_symlink() or not source.is_file() or output.is_symlink():raise ValueError('parser_regular_scoped_paths_required')
 output.mkdir(parents=True,exist_ok=True,mode=0o700);output=output.resolve();source=source.resolve()
 if source.is_relative_to(output):raise ValueError('original_must_be_outside_parser_write_scope')
 lock=output/'host.lock'
 with lock.open('a') as guard:
  try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'status':'busy','model_read':False}
  origin=output/'origin.json';stat=source.stat();signature=[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
  if origin.exists():
   original=json.loads(origin.read_text())
   if original['stat']!=signature:
    # A restored immutable original has a new filesystem identity. Content identity remains authoritative.
    if filehash(source)!=original['sha256']:raise ValueError('original_changed_since_intake')
    approved_path=output/'accepted.json';scratch=output/'scratch';cp=scratch/'checkpoint.json'
    if not approved_path.is_file() or not cp.is_file() or cp.is_symlink():raise ValueError('restored_unsettled_checkpoint_requires_new_parse')
    approved=json.loads(approved_path.read_text());candidate=json.loads(cp.read_text())
    if any(candidate.get(k)!=v for k,v in approved.items() if k not in {'protected_index_bytes','index_sha256','last_execution_receipt'}):raise ValueError('restored_unsettled_checkpoint_requires_new_parse')
    if prefixhash(scratch/'units.jsonl',approved['index_bytes'])!=approved['index_sha256']:raise ValueError('restored_checkpoint_integrity_failed')
    checked=source.stat()
    if [checked.st_dev,checked.st_ino,checked.st_size,checked.st_mtime_ns,checked.st_ctime_ns]!=signature:raise ValueError('original_changed_during_revalidation')
    rebindings=output/'origin-rebindings';rebindings.mkdir(exist_ok=True,mode=0o700)
    reference=rebindings/(uuid.uuid4().hex+'.json');atomic(reference,{'contract':'BNOriginalIdentityRevalidationV1','previous_stat':original['stat'],'current_stat':signature,'original_sha256':original['sha256'],'exact_bytes_rehashed':True,'settled_checkpoint_only':True,'at':time.time()})
    original.setdefault('intake_stat',original['stat']);original['stat']=signature;original['identity_revalidation_ref']=str(reference);atomic(origin,original)
   if original.get('os_release')!=platform.mac_ver()[0] or original.get('worker_sha256')!=filehash(worker) or original.get('format')!=req['format'] or original.get('runtime_pin_sha256')!=filehash(lockfile):raise ValueError('parser_revision_changed_start_new_parse')
   if req.get('expected_sha256') and req['expected_sha256']!=original['sha256']:raise ValueError('original_hash_mismatch')
  else:
   digest=filehash(source)
   if req.get('expected_sha256') and digest!=req['expected_sha256']:raise ValueError('original_hash_mismatch')
   original={'sha256':digest,'bytes':stat.st_size,'stat':signature,'worker_sha256':filehash(worker),'format':req['format'],'runtime_pin_sha256':filehash(lockfile),'os_release':platform.mac_ver()[0]};atomic(origin,original)
  derived=output/'scratch';derived.mkdir(exist_ok=True,mode=0o700)
  final=output/'units';final.mkdir(exist_ok=True,mode=0o700)
  if req['format']=='sqlite':limits['max_file_bytes']=max(limits['max_file_bytes'],stat.st_size*2)
  tmp=derived/'tmp';tmp.mkdir(exist_ok=True,mode=0o700)
  roots=pin['python_roots'];package=worker.parent.parent;reads=[source,package,*map(Path,roots)];execs=[Path(python),Path(python).resolve(),Path('/usr/bin/sandbox-exec')]
  if req.get('xls_java'):reads.append(Path(req['xls_java']).resolve().parents[1]);execs.append(Path(req['xls_java']).resolve())
  ocr=package/'vision-ocr'
  if ocr.is_file():execs.append(ocr)
  sandbox=profile(reads,[derived],execs,compute=req['format']=='pdf',java=req['format']=='xls');sp=output/'sandbox.sb';sp.write_text(sandbox);sp.chmod(0o600)
  payload={**req,'path':str(source),'output':str(derived),'limits':limits,'ocr_binary':str(ocr)}
  env={'PATH':'/usr/bin:/bin','TMPDIR':str(tmp),'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
  accepted_path=output/'accepted.json'
  before=json.loads(accepted_path.read_text()) if accepted_path.exists() else {'units':0,'index_bytes':0}
  index=derived/'units.jsonl'
  if before.get('complete') and before.get('last_execution_receipt'):
   last=Path(before['last_execution_receipt'])
   if last.is_symlink() or last.parent!=output/'parse-receipts':raise ValueError('invalid_cached_execution_reference')
   prior=json.loads(last.read_text());return {**prior,'execution_receipt_ref':str(last),'cached_parser_result':True,'new_executor_launched':False,'original_identity_revalidation_ref':original.get('identity_revalidation_ref')}
  if index.is_symlink():raise ValueError('unsafe_parser_index')
  if before['index_bytes'] and (not index.is_file() or prefixhash(index,before['index_bytes'])!=before['index_sha256']):raise ValueError('committed_parser_index_changed')
  started=time.monotonic();reason=None;run_id=uuid.uuid4().hex
  with tempfile.TemporaryFile(mode='w+') as stdout,tempfile.TemporaryFile(mode='w+') as stderr:
   proc=subprocess.Popen(['/usr/bin/sandbox-exec','-f',str(sp),str(python),'-I','-B',str(worker)],stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True,env=env,start_new_session=True,cwd=output)
   payload['_parent_pid']=os.getpid();payload['_attempt_id']=run_id
   attempts=output/'attempts';attempts.mkdir(exist_ok=True,mode=0o700);atomic(attempts/(run_id+'.started.json'),{'pid':proc.pid,'parent_pid':os.getpid(),'worker_sha256':filehash(worker),'source_sha256':original['sha256'],'state':'started','sandbox_sha256':hashlib.sha256(sandbox.encode()).hexdigest()})
   proc.stdin.write(canonical(payload));proc.stdin.close()
   try:
    while proc.poll() is None:
     if CANCEL_EVENT.get() is not None and CANCEL_EVENT.get().is_set():reason='parser_cancelled';break
     if time.monotonic()-started>limits['step_seconds']+5:reason='parser_step_deadline';break
     ps=subprocess.run(['/bin/ps','-axo','pgid=,rss='],capture_output=True,text=True)
     group=[parts for line in ps.stdout.splitlines() if len(parts:=line.split())==2 and parts[0]==str(proc.pid)]
     if len(group)>limits['max_processes']:reason='parser_step_processes';break
     rss=sum(int(parts[1])*1024 for parts in group)
     if rss>limits['max_rss_bytes']:reason='parser_step_memory';break
     time.sleep(.1)
   finally:
    if proc.poll() is None:
     try:os.killpg(proc.pid,signal.SIGKILL)
     except ProcessLookupError:pass
    proc.wait()
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:pass
   stdout.seek(0);raw=stdout.read(65537);stderr.seek(0);err=stderr.read(2000)
  now=source.stat()
  if [now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns]!=signature:raise ValueError('original_changed_during_parse')
  new_rows=[]
  cp=derived/'checkpoint.json'
  if cp.is_symlink() or (cp.exists() and cp.stat().st_size>65536):raise ValueError('unsafe_parser_checkpoint')
  checkpoint=json.loads(cp.read_text()) if cp.exists() else dict(before)
  if type(checkpoint.get('units')) is not int or checkpoint['units']<before['units'] or type(checkpoint.get('index_bytes',0)) is not int:raise ValueError('invalid_parser_checkpoint')
  if index.is_symlink():raise ValueError('unsafe_parser_index')
  if index.exists():
   with index.open('rb') as f:
    if before['index_bytes'] and prefixhash(index,before['index_bytes'])!=before['index_sha256']:raise ValueError('committed_parser_index_changed')
    f.seek(before['index_bytes'])
    new_rows=[]
    while f.tell()<checkpoint.get('index_bytes',0):
     line=f.readline(2*1024*1024)
     if not line.endswith(b'\n'):raise ValueError('parser_index_line_invalid')
     row=json.loads(line);i=before['units']+len(new_rows)
     if type(row.get('index')) is not int or row.get('index')!=i:raise ValueError('parser_unit_sequence_invalid')
     for suffix,wanted in [('.txt',row.get('text_sha256'))]+([('.png',row.get('image_sha256'))] if row.get('visual_required') else []):
      path=derived/(str(i)+suffix)
      if not path.exists():path=final/path.name
      if path.is_symlink() or not path.is_file() or filehash(path)!=wanted:raise ValueError('parser_output_integrity_failed')
     textfile=derived/(str(i)+'.txt')
     if not textfile.exists():textfile=final/textfile.name
     if textfile.stat().st_size>262144 or len(textfile.read_bytes().decode("utf-8"))!=row.get('characters'):raise ValueError('parser_text_shape_invalid')
     if row.get('visual_required'):
      image=derived/(str(i)+'.png')
      if not image.exists():image=final/image.name
      with image.open('rb') as imagefile:header=imagefile.read(24)
      if header[:8]!=b'\x89PNG\r\n\x1a\n' or int.from_bytes(header[16:20],'big')*int.from_bytes(header[20:24],'big')>20000000:raise ValueError('parser_image_geometry_invalid')
     new_rows.append(row)
    if f.tell()!=checkpoint.get('index_bytes',0) or before['units']+len(new_rows)!=checkpoint['units']:raise ValueError('parser_unit_index_incomplete')
   for row in new_rows:
    for suffix in ['.txt']+(['.png'] if row.get('visual_required') else []):
     src=derived/(str(row['index'])+suffix);dest=final/src.name
     if src.exists():
      if dest.exists() and filehash(src)!=filehash(dest):raise ValueError('parser_committed_output_conflict')
      os.replace(src,dest)
   protected_index=output/'units.jsonl'
   if not protected_index.exists():protected_index.touch(mode=0o600)
   with protected_index.open('r+b') as f:
    f.truncate(before.get('protected_index_bytes',0));f.seek(before.get('protected_index_bytes',0))
    for row in new_rows:f.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
    f.flush();os.fsync(f.fileno())
   protected={**checkpoint,'protected_index_bytes':protected_index.stat().st_size,'index_sha256':prefixhash(index,checkpoint.get('index_bytes',0))}
   atomic(accepted_path,protected)
  now=source.stat()
  if [now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns]!=signature:raise ValueError('original_changed_during_parse')
  try:body=json.loads(raw) if len(raw)<=65536 else {}
  except ValueError:body={}
  if proc.returncode or reason:
   progress=checkpoint['units']>before['units'];body={'status':'partial' if progress else 'blocked','code':reason or body.get('code','parser_process_failed'),'units':checkpoint['units'],'diagnostic':err[-500:],'retry_without_repair':progress}
  if body.get('status') not in {'extracted','partial','blocked'}:raise RuntimeError('parser_response_invalid')
  if body['status']=='extracted' and not checkpoint.get('complete'):raise ValueError('parser_complete_without_committed_eof')
  body['output_directory']=str(final);body['unit_index']=str(output/'units.jsonl')
  body.update(parser_version=VERSION,host_sha256=filehash(Path(__file__)),original_identity_revalidation_ref=original.get('identity_revalidation_ref'),profile_id='parser',original_sha256=original['sha256'],original_bytes=original['bytes'],parser_binary_hash=filehash(Path(python).resolve()),worker_sha256=filehash(worker),configuration_hash=hashlib.sha256(canonical({'limits':limits,'sandbox':sandbox,'format':req['format'],'worker_sha256':filehash(worker),'runtime_pin_sha256':filehash(lockfile),'host_sha256':filehash(Path(__file__)),'os_release':platform.mac_ver()[0]}).encode()).hexdigest(),resource_limits=limits,elapsed_ms=int((time.monotonic()-started)*1000),sandbox_enforced=True,network_allowed=False,credentials_inherited=False,pid=proc.pid,exit_code=proc.returncode,model_read=False,meaning_verified=False)
  receipts=output/'parse-receipts';receipts.mkdir(exist_ok=True,mode=0o700)
  delta=receipts/(run_id+'.units.jsonl')
  with delta.open('x') as f:
   for row in new_rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
   f.flush();os.fsync(f.fileno())
  body.update(execution_receipt_ref=str(receipts/(run_id+'.json')),new_executor_launched=True,units_before=before['units'],units_after=checkpoint['units'],derived_delta_ref=str(delta),derived_delta_sha256=filehash(delta))
  atomic(receipts/(run_id+'.json'),body)
  if accepted_path.exists():
   accepted=json.loads(accepted_path.read_text());accepted['last_execution_receipt']=body['execution_receipt_ref'];atomic(accepted_path,accepted)
  return body
