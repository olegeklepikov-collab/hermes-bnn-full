"""One heavy maintenance producer per managed platform; protect foreground headroom."""
import contextlib,fcntl,functools,json,os,shutil,stat
from pathlib import Path

GIB=1024**3


def admission(available,additional,reserve=6*GIB):
    if any(type(v) is not int or v<0 for v in [available,additional,reserve]):raise ValueError('invalid_storage_capacity')
    if available<additional+reserve:raise OSError('maintenance_capacity_required:free='+str(available)+':additional='+str(additional)+':protected='+str(reserve))
    return {'free':available,'additional':additional,'protected':reserve}


def protected(kind):
    def decorate(fn):
        @functools.wraps(fn)
        def call(*args,**kw):
            environment=args[1] if len(args)>1 else kw.get('environment','test')
            if kind=='qualify' and environment not in {'test','development'}:raise PermissionError('production_is_read_only_in_this_phase')
            import release_cli as r
            cfg=r.resources();base=Path(cfg['build_root']);lock=Path(cfg['development_root'])/'.operator/maintenance-capacity.lock'
            before=set(base.joinpath('candidates').iterdir()) if base.joinpath('candidates').exists() else set()
            lock.parent.mkdir(parents=True,exist_ok=True)
            with lock.open('a') as f:
                try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise RuntimeError('managed_maintenance_capacity_busy')
                if kind=='build':
                    meta=Path(cfg['runtime_cache']).parent/'RELEASE.json';size=json.loads(meta.read_text())['archive']['bytes']
                    extra=int(size*1.1)+128*1024**2
                else:
                    # Native APFS qualification uses an owned clone. Other
                    # platforms must budget the complete independent write.
                    directory=Path(args[0]);meta=json.loads((directory/'RELEASE.json').read_text())
                    extra=GIB if os.uname().sysname=='Darwin' else sum(v.get('bytes',0) for v in json.loads((directory/'Hermes-BNN-Full/bundle-manifest.json').read_text())['objects'].values())
                environment=args[1] if len(args)>1 else kw.get('environment','test')
                target=base if kind=='build' else Path(cfg['environment_roots'][environment])
                admission(shutil.disk_usage(target).free,extra)
                try:return fn(*args,**kw)
                except BaseException:
                    if kind=='build':
                        # Only unfinished output created by this invocation is
                        # expendable. User state and prior artifacts are never GC.
                        for child in set(base.joinpath('candidates').iterdir())-before:
                            for p in child.glob('*.tar.gz.pending'):
                                if not p.is_symlink() and stat.S_ISREG(p.stat().st_mode):p.unlink()
                    raise
        return call
    return decorate
