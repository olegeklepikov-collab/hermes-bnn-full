"""Regular-file and durable-write primitives retained from foundation 0.1.0."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

RESERVED = ('continuity','foundations','epistemic_stance','values_and_boundaries',
            'dispositions','relationships','expression')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_regular(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as handle:
        info=os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('regular_unlinked_identity_file_required')
        return handle.read()


def save_new(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as handle:
        handle.write(data);handle.flush();os.fsync(handle.fileno())


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


@contextlib.contextmanager
def locked(root):
    fd=os.open(Path(root)/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX);yield
    finally:os.close(fd)
