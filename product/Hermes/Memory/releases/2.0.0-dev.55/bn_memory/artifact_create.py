"""Candidate immutable text-file creator. Installed in the release only at an idle boundary."""
import os,stat
from pathlib import Path
from bn_memory.store import canonical,sha

def create(artifacts,sid,args,*,project=None):
    store=artifacts.store;binding=store.writable(sid)
    name=args['file_name'];content=args['content'];request=args['request_id']
    if (not isinstance(name,str) or not 1<=len(name)<=128 or Path(name).name!=name or '/' in name or '\\' in name
        or name.startswith('.') or any(ord(c)<32 for c in name) or Path(name).suffix.lower() not in {'.md','.txt'}
        or name.upper() in {'SOUL.MD','AGENTS.MD','MEMORY.MD','USER.MD','SYSTEM.MD'}):
        raise PermissionError('generated_result_name_invalid')
    if not isinstance(content,str) or not content or len(content)>262144:
        raise ValueError('split_generated_result_without_trimming')
    data=content.encode();artifacts.sensitive(data,artifacts.secrets())
    fingerprint=sha(canonical(args));identifier='GEN-'+sha(canonical([store.profile,sid,request]))[:24]
    # Internal native completion may arrive after the foreground changed tasks.
    # The saved result keeps its launch project. This keyword is not a model arg.
    project=binding['project'] if project is None else project
    if project not in artifacts.cfg['projects']:raise PermissionError('result_project_not_owned')
    root=Path(artifacts.cfg['projects'][project]).resolve()
    target=root/'deliverables'/identifier/name
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS artifact_creations(profile_id TEXT,sid TEXT,id TEXT,input_hash TEXT,path TEXT,PRIMARY KEY(profile_id,sid,id))')
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT input_hash,path FROM artifact_creations WHERE profile_id=? AND sid=? AND id=?',(store.profile,sid,request)).fetchone()
        if old and (old[0]!=fingerprint or old[1]!=str(target)):raise ValueError('artifact_creation_input_conflict')
        if not old:db.execute('INSERT INTO artifact_creations VALUES(?,?,?,?,?)',(store.profile,sid,request,fingerprint,str(target)))
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW;directory=os.open(root,flags)
    try:
        for part in ['deliverables',identifier]:
            try:os.mkdir(part,0o700,dir_fd=directory)
            except FileExistsError:pass
            try:nextfd=os.open(part,flags,dir_fd=directory)
            except OSError as exc:raise PermissionError('generated_directory_not_owned_regular_path') from exc
            os.close(directory);directory=nextfd
        duplicate=False
        try:fd=os.open(name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=directory)
        except FileExistsError:
            duplicate=True;fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
            with os.fdopen(fd,'rb') as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode) or f.read(len(data)+1)!=data:
                    raise PermissionError('generated_previous_outcome_requires_observation_no_overwrite')
        else:
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.fsync(directory)
    finally:os.close(directory)
    result=artifacts.register(sid,{'action':'register','path':str(target),'request_id':'created-'+identifier,'expected_sha256':sha(content)})
    return {**result,'duplicate':duplicate,'created_file':True,'generated_content_status':'unreviewed','overwritten_existing_file':False,'network_calls':0}
