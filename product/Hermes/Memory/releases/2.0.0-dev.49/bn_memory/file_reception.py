"""Exact addressed file pages observed in physical input + a provider response.

This is transport/reception coverage, never a claim of semantic understanding.
Only assigned files, actual function-output rows and current source bytes qualify.
"""
import json
from pathlib import Path
from bn_memory.store import canonical,sha


def pages(value,depth=0):
    if depth>5:return
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:
            starts=[i for i in [value.find('{'),value.find('[')] if i>=0]
            if not starts or min(starts)>512:return
            try:value=json.JSONDecoder().raw_decode(value[min(starts):])[0]
            except ValueError:return
        if isinstance(value,str):
            yield from pages(value,depth+1)
            return
    if isinstance(value,list):
        for item in value:yield from pages(item,depth+1)
    elif isinstance(value,dict):
        if {'source_path','source_sha256','offset','text','has_more'}<=set(value):
            yield value;return  # The source text is data, not a nested receipt.
        for key in ['content','text','output','result']:
            if key in value:yield from pages(value[key],depth+1)


def observed(host,sid,request):
    binding=host.store.binding(sid)
    if not binding['readonly'] or not host.config.get('w3_enabled'):return []
    from bn_memory.assignment_resources import read
    assigned=read(host.store,binding)['files'];calls={};result=[]
    for item in request.get('messages',request.get('input',[])):
        if not isinstance(item,dict):continue
        if item.get('type')=='function_call':calls[item.get('call_id')]=item.get('name')
        for call in item.get('tool_calls') or []:calls[call.get('id')]=(call.get('function') or {}).get('name')
        identifier=item.get('call_id') if item.get('type')=='function_call_output' else item.get('tool_call_id') if item.get('role')=='tool' else None
        name=calls.get(identifier) or item.get('name','')
        if not identifier or name not in {'memory_files','mcp__context__memory_files'}:continue
        for page in pages(item.get('output',item.get('content'))):
            path=page['source_path'];start=page['offset'];text=page['text'];expected=assigned.get(path)
            if (not expected or type(start) is not int or start<0 or not isinstance(text,str)
                    or page['source_sha256']!=expected['sha256']):continue
            from bn_memory.source_visibility import read_file
            raw,digest=read_file(Path(path),max_bytes=host.config.get('file_source_bytes',8*1024*1024))
            original=raw.decode('utf8');end=start+len(text)
            if digest!=expected['sha256'] or original[start:end]!=text:raise PermissionError('assigned_file_reception_source_changed')
            if type(page['has_more']) is not bool or page['has_more']!=(end<len(original)):
                raise PermissionError('file_page_requires_exact_addressed_output')
            result.append({'assignment':binding['assignment_id'],'path':path,'source_sha256':digest,
                           'offset':start,'end':start+len(text),'fragment_sha256':sha(text),'call_id':identifier,
                           'eof':page['has_more'] is False,'request_sha256':sha(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}}))})
    return result


def received(host,sid,items):
    if not items:return
    with host.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS native_file_receptions(profile_id TEXT,sid TEXT,id TEXT,body TEXT,PRIMARY KEY(profile_id,sid,id))')
        for item in items:
            key=sha(canonical({k:v for k,v in item.items() if k!='request_sha256'}))
            db.execute('INSERT OR IGNORE INTO native_file_receptions VALUES(?,?,?,?)',(host.store.profile,sid,key,canonical(item)))


def complete(host,child):
    binding=host.store.binding(child)
    from bn_memory.assignment_resources import read
    assigned=read(host.store,binding)['files'];proof={}
    with host.store.db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='native_file_receptions'").fetchone()
        items=[json.loads(r[0]) for r in db.execute('SELECT body FROM native_file_receptions WHERE profile_id=? AND sid=?',(host.store.profile,child))] if exists else []
    for path,version in assigned.items():
        position=0;eof=False
        for item in sorted((x for x in items if x['path']==path and x['source_sha256']==version['sha256']),key=lambda x:x['offset']):
            if item['offset']>position:break
            position=max(position,item['end']);eof=eof or item['eof'] and item['end']==position
        from bn_memory.source_visibility import hash_file
        current=hash_file(Path(path))==version['sha256']
        proof[path]={'received_chars':position,'eof':eof,'source_current':current,'complete':eof and current}
    return {'complete':all(x['complete'] for x in proof.values()),'files':proof,
            'coverage':'native tool pages present in physical requests with provider responses; not semantic acceptance'}
