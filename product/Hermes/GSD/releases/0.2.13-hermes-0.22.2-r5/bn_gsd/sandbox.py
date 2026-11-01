"""Native terminal provider backed by macOS Seatbelt, not command-pattern filtering."""
from pathlib import Path
import hashlib, json, os, subprocess, sys


def temporary(settings):
    p=Path(settings["r_runtime"])/"tmp/gsd"/hashlib.sha256(settings["workspace"].encode()).hexdigest()[:16]
    p.mkdir(mode=0o700,parents=True,exist_ok=True);return p


def profile(settings):
    workspace=Path(settings['workspace']).resolve()
    runtime=Path(settings['runtime_root']).resolve()
    reads=['/etc','/var/db/dyld','/private/var/db/dyld','/System/Volumes/Preboot','/private/preboot','/System','/usr','/bin','/sbin','/private/etc','/Library/Apple',str(runtime/'runtime'),str((runtime/'hermes-agent').resolve()),str(runtime/'R'),str(Path(settings['r_runtime'])/'env'),str(Path(settings['r_runtime'])/'library'),str(Path(settings['bundle_root']).resolve()),str(workspace),str(temporary(settings))]
    if settings.get('r_native_home'):reads.extend([settings['r_native_home'],'/Library/Frameworks/R.framework','/opt/R/arm64',str(Path(settings['r_runtime'])/'library-native')])
    from .paths import public_read_roots
    reads.extend(str(p) for p in public_read_roots(settings))
    writes=[str(workspace),str(workspace/'.gsd-sandbox-tmp'),str(runtime/'R/projects'),str(runtime/'R/exports'),str(temporary(settings))]
    def rule(op,paths): return '(allow '+op+' '+ ' '.join('(subpath '+json.dumps(p)+')' for p in paths)+')'
    return '\n'.join(['(version 1)','(deny default)','(allow process-exec process-fork)','(allow signal (target self))','(allow sysctl-read)', '(allow file-read-metadata)','(allow file-read* (literal "/"))',rule('file-read*',reads),rule('file-write*',writes),'(deny file-write* (subpath '+json.dumps(str(workspace/'artifacts'))+'))','(allow file-read-data file-write-data (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))'])


def environment(settings):
    from tools.environments.local import served_profile_child_env
    from hermes_constants import get_hermes_home
    env=served_profile_child_env(target_home=get_hermes_home(),inherit_credentials=False)
    # An explicit minimal process environment removes inherited shell functions and integration keys.
    root=Path(settings['runtime_root']); workspace=Path(settings['workspace'])
    temp=workspace/'.gsd-sandbox-tmp'; temp.mkdir(mode=0o700,exist_ok=True)
    return {'PATH':str(root/'hermes-agent/venv/bin')+':'+str(root/'R/bin')+':/usr/bin:/bin:/usr/sbin:/sbin',
            'HOME':str(workspace),'TMPDIR':str(temporary(settings)),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1',
            'HERMES_BN_R_HOME':str(root/'R'),'R_LIBS_USER':str(Path(settings['r_runtime'])/('library-native' if settings.get('r_native_home') else 'library')),'R_HOME':settings.get('r_native_home',str(Path(settings['r_runtime'])/'env/lib/R')),'R_LIBS_SITE':str(Path(settings.get('r_native_home',str(Path(settings['r_runtime'])/'env/lib/R')))/'library'),
            'LANG':env.get('LANG','en_US.UTF-8')}


def provider(settings):
    from agent.terminal_env_provider import TerminalEnvironmentProvider
    from tools.environments.local import LocalEnvironment
    from tools.environments.base import BaseEnvironment
    from tools.environments.base_output import _pipe_stdin
    class SandboxedLocal(BaseEnvironment):
        is_local=False
        _kill_process=LocalEnvironment._kill_process
        _force_kill_process=LocalEnvironment._force_kill_process
        _extract_cwd_from_output=BaseEnvironment._extract_cwd_from_output
        cleanup=LocalEnvironment.cleanup
        def __init__(self,cwd,timeout,env):
            super().__init__(cwd=cwd,timeout=timeout,env=env)
            self.init_session()
        def get_temp_dir(self):
            p=Path(settings['workspace'])/'.gsd-sandbox-tmp';p.mkdir(mode=0o700,exist_ok=True);return str(p)
        def _run_bash(self,cmd_string,*,login=False,timeout=120,stdin_data=None):
            cwd=Path(self.cwd).resolve()
            if not cwd.is_relative_to(Path(settings['workspace']).resolve()):
                cwd=Path(settings['workspace']);self.cwd=str(cwd)
            proc=subprocess.Popen(['/usr/bin/sandbox-exec','-p',profile(settings),'/bin/bash','--noprofile','--norc','-c',cmd_string],
                text=True,encoding='utf-8',errors='replace',env=environment(settings),cwd=cwd,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,start_new_session=True)
            proc._hermes_pgid=os.getpgid(proc.pid)
            if stdin_data is not None:_pipe_stdin(proc,stdin_data)
            return proc
    class Provider(TerminalEnvironmentProvider):
        name='bn_guarded_local';is_remote=False;is_container=False
        def is_available(self):return sys.platform=='darwin' and Path('/usr/bin/sandbox-exec').is_file()
        def create_environment(self,*,cwd,timeout,**kw):
            if not self.is_available():raise RuntimeError('Mandatory OS sandbox unavailable')
            return SandboxedLocal(cwd=str(Path(settings['workspace'])),timeout=min(timeout,240),env=environment(settings))
    return Provider()
