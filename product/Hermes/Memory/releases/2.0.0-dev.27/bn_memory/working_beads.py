"""Pinned, read-only primary-task lookup. Task creation/planning stays in Beads."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from bn_memory.store import canonical,SENSITIVE
_verified_files={}


def lookup(config,identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',identifier):
        raise ValueError('primary_task_id_invalid')
    settings=config.get('working_beads')
    if not isinstance(settings,dict) or not settings.get('files'):
        raise PermissionError('working_primary_adapter_unconfigured')
    command=Path(settings['command'])
    if str(command) not in settings['files']:raise PermissionError('working_primary_command_not_pinned')
    for name,expected in settings['files'].items():
        path=Path(name)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise PermissionError('working_primary_file_invalid')
        st=path.stat();stamp=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,expected)
        if _verified_files.get(name)!=stamp:
            with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected:raise PermissionError('working_primary_code_changed')
            _verified_files[name]=stamp
    result=subprocess.run([str(command),'show',identifier,'--json'],capture_output=True,text=True,timeout=15)
    if result.returncode:raise PermissionError('working_primary_lookup_failed')
    rows=json.loads(result.stdout)
    if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('id')!=identifier or 'revision' not in rows[0]:
        raise PermissionError('working_primary_reference_invalid')
    selected={key:rows[0].get(key) for key in ['id','revision','title','description','status']}
    if SENSITIVE.search(canonical(selected)):raise PermissionError('private_primary_task_not_context')
    return {'system':'beads','id':identifier,'revision':str(selected['revision']),
            'sha256':hashlib.sha256(canonical(selected).encode()).hexdigest(),
            'title':selected['title'],'status':selected['status'],'semantic_review':'not_performed'}
