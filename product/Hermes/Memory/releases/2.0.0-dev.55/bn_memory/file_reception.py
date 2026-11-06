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
    assigned=read(host.store,binding)['files'];calls={};result=[];sources={};request_hash=None
    file_tools={'memory_files','mcp__context__memory_files'}
    def methods(name,arguments=None):
        if name in file_tools:return {name}
        if name!='tool_call':return set()
        try:value=json.loads(arguments) if isinstance(arguments,str) else arguments
        except ValueError:return set()
        if not isinstance(value,dict) or not isinstance(value.get('calls'),list):return set()
        names={x.get('name') for x in value['calls'] if isinstance(x,dict)}
        # Mixed-method bridge results need a per-result dispatch witness. Until
        # available, do not credit text returned by a different method.
        return names if names and names<=file_tools else set()
    for item in request.get('messages',request.get('input',[])):
        if not isinstance(item,dict):continue
        if item.get('type')=='function_call':calls[item.get('call_id')]=methods(item.get('name'),item.get('arguments'))
        for call in item.get('tool_calls') or []:
            fn=call.get('function') or {};calls[call.get('id')]=methods(fn.get('name'),fn.get('arguments'))
        identifier=item.get('call_id') if item.get('type')=='function_call_output' else item.get('tool_call_id') if item.get('role')=='tool' else None
        names=calls.get(identifier) or methods(item.get('name',''))
        if not identifier or not names:continue
        for page in pages(item.get('output',item.get('content'))):
            path=page['source_path'];start=page['offset'];text=page['text'];expected=assigned.get(path)
            if (not expected or type(start) is not int or start<0 or not isinstance(text,str)
                    or page['source_sha256']!=expected['sha256']):continue
            from bn_memory.source_visibility import read_file
            if path not in sources:
                raw,digest=read_file(Path(path),max_bytes=host.config.get('file_source_bytes',8*1024*1024))
                if digest!=expected['sha256']:raise PermissionError('assigned_file_reception_source_changed')
                sources[path]=(raw.decode('utf8'),digest)
            original,digest=sources[path];end=start+len(text);fragment=original[start:end]
            projection='identity'
            if fragment!=text:
                # Old persisted tool messages contain this deterministic native
                # projection. It is not an edit of the assigned source file.
                from agent.tool_dispatch_helpers import _DELIMITER_TOKEN_RE
                if _DELIMITER_TOKEN_RE.sub('untrusted-tool-result',fragment)!=text:
                    raise PermissionError('assigned_file_reception_payload_changed')
                projection='native_untrusted_delimiter_legacy_v1'
            if type(page['has_more']) is not bool or page['has_more']!=(end<len(original)):
                raise PermissionError('file_page_requires_exact_addressed_output')
            if request_hash is None:
                request_hash=sha(canonical({k:v for k,v in request.items() if k not in {'timeout','http_client'}}))
            result.append({'assignment':binding['assignment_id'],'path':path,'source_sha256':digest,
                           'offset':start,'end':start+len(text),'fragment_sha256':sha(text),'call_id':identifier,
                           'source_fragment_sha256':sha(fragment),'delivery_projection':projection,
                           'eof':page['has_more'] is False,'request_sha256':request_hash})
    return result


def received(host,sid,items):
    if not items:return
    with host.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS native_file_receptions(profile_id TEXT,sid TEXT,id TEXT,body TEXT,PRIMARY KEY(profile_id,sid,id))')
        for item in items:
            key=sha(canonical({k:v for k,v in item.items() if k!='request_sha256'}))
            db.execute('INSERT OR IGNORE INTO native_file_receptions VALUES(?,?,?,?)',(host.store.profile,sid,key,canonical(item)))


def _coverage(items):
    position=0;eof=False
    for item in sorted(items,key=lambda value:value['offset']):
        if item['offset']>position:break
        position=max(position,item['end']);eof=eof or item['eof'] and item['end']==position
    return position,eof


def complete(host,child):
    binding=host.store.binding(child)
    from bn_memory.assignment_resources import read
    assigned=read(host.store,binding)['files'];proof={}
    with host.store.db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='native_file_receptions'").fetchone()
        items=[json.loads(r[0]) for r in db.execute('SELECT body FROM native_file_receptions WHERE profile_id=? AND sid=?',(host.store.profile,child))] if exists else []
    for path,version in assigned.items():
        matching=[x for x in items if x['path']==path and x['source_sha256']==version['sha256']]
        position,eof=_coverage(matching)
        exact_position,exact_eof=_coverage(x for x in matching if x.get('delivery_projection','identity')=='identity')
        from bn_memory.source_visibility import hash_file
        current=hash_file(Path(path))==version['sha256']
        projections=sorted({x.get('delivery_projection','identity') for x in matching})
        proof[path]={'received_chars':position,'eof':eof,'source_current':current,'complete':eof and current,
                     'delivery_projections':projections,
                     'exact_decoded_text':bool(current and exact_eof and exact_position>=position)}
    return {'complete':all(x['complete'] for x in proof.values()),'files':proof,
            'coverage':'native tool pages present in physical requests with provider responses; not semantic acceptance'}
