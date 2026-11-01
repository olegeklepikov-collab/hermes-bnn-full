"""Executed only inside the mandatory OS sandbox, with isolated standard-library Python."""
import errno
import json
import os
from pathlib import Path
import resource
import socket
import sys


def denied(operation):
    try:operation()
    except OSError as exc:return exc.errno in {errno.EPERM,errno.EACCES,errno.EAGAIN}
    return False


def limits(value):
    for name,amount in [('RLIMIT_CORE',0),('RLIMIT_FSIZE',value['output_bytes']),
                        ('RLIMIT_CPU',value['step_seconds']+2),('RLIMIT_NOFILE',64),('RLIMIT_NPROC',0)]:
        key=getattr(resource,name,None)
        if key is not None:resource.setrlimit(key,(amount,amount))


def probe(req):
    def read_private():
        with open(req['canary'],'rb') as handle:handle.read(1)
    def write_private():
        fd=os.open(req['canary'],os.O_WRONLY|os.O_TRUNC);os.close(fd)
    def connect():
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            sock.settimeout(.3);sock.connect(('127.0.0.1',9))
    def fork():
        pid=os.fork()
        if pid==0:os._exit(0)
        os.waitpid(pid,0)
    def inspect_parent():
        import ctypes
        library=ctypes.CDLL(None,use_errno=True)
        query=(ctypes.c_int*3)(1,49,os.getppid())
        size=ctypes.c_size_t()
        # Ask only for size; never read the real parent's arguments/environment.
        code=library.sysctl(query,3,None,ctypes.byref(size),None,0)
        return code==-1 and ctypes.get_errno() in {errno.EPERM,errno.EACCES}
    checks={'private_read_denied':denied(read_private),'private_write_denied':denied(write_private),
            'network_denied':denied(connect),'fork_denied':denied(fork),'other_process_info_denied':inspect_parent()}
    print(json.dumps(checks));return 0 if all(checks.values()) else 3


def main():
    req=json.load(sys.stdin);limits(req['limits'])
    if req['mode']=='probe':return probe(req)
    if req['mode']!='run':raise ValueError('compute_worker_mode_invalid')
    data=json.loads(Path(req['input']).read_text())
    script=Path(req['script']).read_text()
    sys.stdin.close();sys.stdin=open(os.devnull)
    # Inputs are DATA; no host keys, callbacks, controller or configuration is passed.
    exec(compile(script,'<assigned-computation>','exec'),{'__name__':'__main__','INPUT':data})
    return 0


if __name__=='__main__':raise SystemExit(main())
