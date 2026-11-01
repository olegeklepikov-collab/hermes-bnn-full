"""Mandatory macOS confinement before untrusted computation. No unsandboxed fallback."""
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import tempfile
import time

CANCEL_EVENT=ContextVar('bn_compute_cancel',default=None)


def filehash(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def runtime(config):
    root=Path(__file__).resolve().parents[1];path=root/'compute-runtime.json'
    if path.is_symlink() or not path.is_file():raise RuntimeError('compute_runtime_not_admitted')
    pin=json.loads(path.read_text());python=Path(config['compute_python']).resolve(strict=True)
    if (platform.system()!='Darwin' or platform.machine()!='arm64' or platform.mac_ver()[0]!=pin['os_release']
            or str(python)!=pin['python'] or filehash(python)!=pin['python_sha256']
            or filehash('/usr/bin/sandbox-exec')!=pin['sandbox_sha256']):
        raise RuntimeError('required_compute_os_or_runtime_mismatch')
    return pin


def profile(pin,script,inputs,worker):
    def rule(kind,path):return '('+kind+' '+json.dumps(str(Path(path).resolve()),ensure_ascii=False)+')'
    reads=[rule('subpath',p) for p in ['/System','/usr/lib','/private/var/db/dyld','/private/var/db/timezone',pin['runtime_root']]]
    reads += [rule('literal',p) for p in [script,inputs,worker,'/dev/null','/dev/urandom','/dev/random','/dev/zero']]
    parents={parent for path in [Path(script),Path(inputs),Path(worker),Path(pin['runtime_root'])] for parent in path.parents}
    reads += [rule('literal',p) for p in sorted(parents)]
    return ('(version 1)(deny default)(deny process-info*)(allow process-info* (target self))(allow file-read-metadata)'
            '(allow sysctl-read (sysctl-name-regex "^(hw[.].*|machdep[.]cpu[.].*|kern[.](os.*|hostname|argmax|version|boottime|maxfiles.*|maxproc.*)|sysctl[.].*)$"))(allow file-read-data (require-any '+' '.join(reads)+'))'
            '(allow file-write* (literal "/dev/null"))'
            '(allow process-exec '+rule('literal',pin['python'])+')')


def launch(pin,sandbox,worker,payload,job,*,started=None):
    limits=payload['limits'];reason=None;begin=time.monotonic()
    with tempfile.TemporaryFile(mode='w+b') as stdout,tempfile.TemporaryFile(mode='w+b') as stderr:
        process=subprocess.Popen(['/usr/bin/sandbox-exec','-p',sandbox,pin['python'],'-I','-S','-B',str(worker)],
            stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,cwd=job,env={'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8'},
            start_new_session=True,close_fds=True)
        try:
            if started:started({'pid':process.pid,'phase':payload['mode']})
            process.stdin.write(json.dumps(payload,ensure_ascii=False).encode());process.stdin.close()
            while process.poll() is None:
                cancel=CANCEL_EVENT.get()
                if cancel is not None and cancel.is_set():reason='compute_cancelled';break
                if time.monotonic()-begin>limits['step_seconds']:reason='compute_step_deadline';break
                value=subprocess.run(['/bin/ps','-o','rss=','-p',str(process.pid)],capture_output=True,text=True,check=False)
                if value.stdout.strip() and int(value.stdout.strip())*1024>limits['rss_bytes']:reason='compute_memory_limit';break
                time.sleep(.03)
        finally:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            process.wait()
        stdout.seek(0);out=stdout.read(limits['output_bytes']+1)
        stderr.seek(0);err=stderr.read(limits['output_bytes']+1)
    if len(out)>=limits['output_bytes'] or len(err)>=limits['output_bytes'] or process.returncode in {-signal.SIGXFSZ,-signal.SIGXCPU}:
        reason=reason or 'compute_resource_limit'
    return {'exit_code':process.returncode,'reason':reason,'stdout':out,'stderr':err,'elapsed_ms':round(1000*(time.monotonic()-begin)),'pid':process.pid}


def run(config,job,script,inputs,*,before_script=None,started=None):
    if CANCEL_EVENT.get() is not None and CANCEL_EVENT.get().is_set():raise RuntimeError('compute_cancelled_before_probe')
    pin=runtime(config);worker=Path(__file__).with_name('compute_worker.py')
    limits={'step_seconds':60,'rss_bytes':512*1024*1024,'output_bytes':2*1024*1024,**config.get('compute_limits',{})}
    if set(limits)!={'step_seconds','rss_bytes','output_bytes'} or any(type(x) is not int or x<=0 for x in limits.values()):
        raise ValueError('compute_limits_invalid')
    sandbox=profile(pin,script,inputs,worker);sandbox_hash=hashlib.sha256(sandbox.encode()).hexdigest()
    canary=job/'control/private-canary';canary.write_bytes(os.urandom(48));canary.chmod(0o600)
    probe=launch(pin,sandbox,worker,{'mode':'probe','canary':str(canary),'limits':limits},job,started=started)
    if probe['exit_code'] or probe['reason']:raise RuntimeError('required_compute_probe_failed')
    try:checks=json.loads(probe['stdout'])
    except ValueError as exc:raise RuntimeError('required_compute_probe_invalid') from exc
    if set(checks)!={'private_read_denied','private_write_denied','network_denied','fork_denied','other_process_info_denied'} or not all(v is True for v in checks.values()):
        raise RuntimeError('required_compute_probe_failed')
    if CANCEL_EVENT.get() is not None and CANCEL_EVENT.get().is_set():raise RuntimeError('compute_cancelled_before_script')
    if before_script:before_script()
    result=launch(pin,sandbox,worker,{'mode':'run','input':str(inputs),'script':str(script),'limits':limits},job,started=started)
    return {**result,'probe':checks,'probe_pid':probe['pid'],'sandbox_sha256':sandbox_hash,'worker_sha256':filehash(worker),
            'python_sha256':pin['python_sha256'],'runtime_pin_sha256':filehash(Path(__file__).resolve().parents[1]/'compute-runtime.json'),
            'os_isolation':True,'network_allowed':False,'file_writes_allowed':False,'credentials_inherited':False,
            'limits':limits,'scope':'assigned input and isolated standard-library Python only'}
