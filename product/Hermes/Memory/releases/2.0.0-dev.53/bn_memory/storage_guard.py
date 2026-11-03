"""Capacity admission for critical state and optional producers. No user-data GC.

The reserve is owned scratch space, released only for local finalization. Remote
actions are never retried here. Separate folders on one device are one domain.
"""
import argparse,errno,json,logging,os,sqlite3,stat,tempfile,time
from pathlib import Path

MAGIC=b'BNN-STORAGE-RESERVE-V1\n'
LOG=logging.getLogger('bnn.storage')


class StorageUnavailable(RuntimeError):
    def __init__(self,code,details=None):
        self.code=code;self.details=details or {}
        super().__init__(code+(':'+json.dumps(self.details,sort_keys=True,separators=(',',':')) if self.details else ''))


def fault(exc):
    if isinstance(exc,StorageUnavailable):return exc.code
    if isinstance(exc,sqlite3.Error):
        code=getattr(exc,'sqlite_errorcode',None)
        if type(code) is int and code&255 in {sqlite3.SQLITE_IOERR,sqlite3.SQLITE_FULL,sqlite3.SQLITE_READONLY,sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB,sqlite3.SQLITE_CANTOPEN}:
            return 'storage_database_'+getattr(exc,'sqlite_errorname','SQLITE_ERROR')
    if isinstance(exc,OSError) and exc.errno in {errno.ENOSPC,errno.EDQUOT,errno.EIO,errno.EROFS,errno.ENODEV,errno.ESTALE}:
        return 'storage_filesystem_'+errno.errorcode.get(exc.errno,'ERROR')
    return None


class Storage:
    def __init__(self,config):
        self.config=config;self.policy=config.get('storage_policy');self.enabled=self.policy is not None
        self.roots={};self.last_probe=0
        if not self.enabled:return
        expected={'version','primary_free_bytes','background_free_bytes','reserve_bytes','probe_interval_seconds'}
        p=self.policy
        if set(p)!=expected or type(p['version']) is not int or p['version']!=1 or any(type(p[k]) is not int or p[k]<=0 for k in expected-{'version'}):raise ValueError('storage_policy_invalid')
        if p['background_free_bytes']<p['primary_free_bytes'] or p['reserve_bytes']>p['primary_free_bytes']:raise ValueError('storage_policy_invalid_watermarks')
        for name,path in [('control',config['state_root']),('profile',config['profile_home'])]:
            root=Path(path);self.roots[name]=(root,root.stat().st_dev if root.is_dir() else None)

    def status(self):
        if not self.enabled:return {'enabled':False,'legacy_profile':True}
        domains={}
        for name,(root,original_device) in self.roots.items():
            if root.is_symlink() or not root.is_dir():raise StorageUnavailable('storage_path_unavailable',{'role':name})
            current=root.stat()
            if original_device is None or current.st_dev!=original_device:raise StorageUnavailable('storage_volume_changed',{'role':name})
            v=os.statvfs(root);free=v.f_bavail*v.f_frsize
            if v.f_flag & getattr(os,'ST_RDONLY',1):raise StorageUnavailable('storage_read_only',{'role':name})
            entry=domains.setdefault(str(current.st_dev),{'roles':[],'free_bytes':free,'capacity_bytes':v.f_blocks*v.f_frsize})
            entry['roles'].append(name);entry['free_bytes']=min(entry['free_bytes'],free)
        return {'enabled':True,'domains':domains,'same_device_is_shared_capacity':True,'policy':self.policy}

    def require(self,kind='primary',extra_bytes=0,probe=False):
        if not self.enabled:return
        if kind not in {'primary','background','evidence'} or type(extra_bytes) is not int or extra_bytes<0:raise ValueError('storage_admission_invalid')
        report=self.status();floor=self.policy['primary_free_bytes' if kind=='primary' else 'background_free_bytes']
        for value in report['domains'].values():
            if value['free_bytes']<floor+extra_bytes:
                raise StorageUnavailable('storage_low_space',{'class':kind,'free_MiB':value['free_bytes']//1048576,'required_MiB':(floor+extra_bytes+1048575)//1048576})
        if probe and time.monotonic()-self.last_probe>=self.policy['probe_interval_seconds']:
            root=self.roots['control'][0]
            try:
                with tempfile.TemporaryFile(dir=root,prefix='.bnn-storage-probe-') as f:
                    f.write(MAGIC);f.flush();os.fsync(f.fileno());f.seek(0)
                    if f.read()!=MAGIC:raise StorageUnavailable('storage_probe_mismatch')
                self.last_probe=time.monotonic()
            except OSError as exc:raise StorageUnavailable(fault(exc) or 'storage_probe_failed',{'errno':exc.errno}) from exc

    @property
    def reserve(self):return Path(self.config['state_root'])/'.bnn-finalization-reserve'

    def _owned_reserve(self):
        p=self.reserve
        try:s=p.lstat()
        except FileNotFoundError:return False
        if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid():raise StorageUnavailable('storage_reserve_not_owned')
        with p.open('rb') as f:
            if f.read(len(MAGIC))!=MAGIC:raise StorageUnavailable('storage_reserve_invalid')
        return True

    def ensure_reserve(self):
        if not self.enabled:return
        import fcntl
        root=self.roots['control'][0];self.require('primary',probe=True)
        with (root/'.bnn-reserve.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise StorageUnavailable('storage_reserve_preparing')
            if self._owned_reserve():
                s=self.reserve.stat()
                if s.st_size==self.policy['reserve_bytes'] and s.st_blocks*512>=s.st_size:return
                # Only our interrupted scratch allocation is replaceable.
                self.reserve.unlink()
            self.require('primary',extra_bytes=self.policy['reserve_bytes'])
            fd=os.open(self.reserve,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            created=os.fstat(fd)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(MAGIC);left=self.policy['reserve_bytes']-len(MAGIC)
                    while left:
                        size=min(left,1048576);f.write(os.urandom(size));left-=size
                    f.flush();os.fsync(f.fileno())
                if self.reserve.stat().st_blocks*512<self.policy['reserve_bytes']:raise StorageUnavailable('storage_reserve_not_physically_allocated')
            except BaseException:
                try:
                    current=self.reserve.lstat()
                    if (current.st_dev,current.st_ino)==(created.st_dev,created.st_ino):self.reserve.unlink()
                except FileNotFoundError:pass
                raise

    def release_reserve(self):
        if not self.enabled or not self._owned_reserve():return False
        try:self.reserve.unlink()
        except FileNotFoundError:return False
        LOG.error('Finalization reserve released; no new dispatch until capacity recovers');return True

    def finalizing(self):
        if not self.enabled:return
        try:low=any(v['free_bytes']<self.policy['reserve_bytes'] for v in self.status()['domains'].values())
        except (OSError,StorageUnavailable):low=True
        if low:self.release_reserve()

    def persist(self,callback):
        """Only an explicitly idempotent LOCAL settlement callback belongs here."""
        self.finalizing()
        try:return callback()
        except (sqlite3.Error,OSError) as exc:
            if fault(exc) and self.release_reserve():return callback()
            raise


def denied(exc,phase,effects=False):
    from hermes_cli.execution_control import ExecutionControlDenied
    code=fault(exc)
    if not code:return None
    LOG.error('Storage failure phase=%s code=%s sqlite_code=%s errno=%s effects_possible=%s',phase,code,getattr(exc,'sqlite_errorcode',None),getattr(exc,'errno',None),effects)
    e=ExecutionControlDenied(code+':phase='+phase+(':effects_may_have_run' if effects else ':before_dispatch'))
    e.effects_may_have_run=effects;e.storage_failure=code;return e


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','check']);p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    s=Storage(json.loads(a.config.read_text()))
    if a.action=='check':s.require('primary',probe=True)
    print(json.dumps(s.status(),ensure_ascii=False))

if __name__=='__main__':main()
