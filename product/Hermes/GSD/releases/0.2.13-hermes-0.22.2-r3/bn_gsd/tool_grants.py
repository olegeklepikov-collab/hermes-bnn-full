"""Exact owner grants, consumed before a protected MCP call; not exposed to models."""
from pathlib import Path
import hashlib,hmac,secrets,time
from .codec import canonical,digest,read_json


def issue(settings,ledger,sid,name,arguments,ttl,reason):
    if not name.startswith('mcp__') or not reason.strip() or type(ttl) is not int or not 1<=ttl<=3600:raise ValueError('Exact operation, reason and bounded lifetime required')
    family=ledger.lookup(sid)['session']['family'];identifier=secrets.token_hex(16)
    body={'version':1,'id':identifier,'family':family,'name':name,'args_digest':digest(arguments),'deadline':time.time()+ttl,'reason':reason}
    value={'body':body,'mac':hmac.new(Path(settings['grant_key']).read_bytes(),canonical(body),hashlib.sha256).hexdigest()}
    p=Path(settings['operator_dir'])/'tool-grants';p.mkdir(mode=0o700,exist_ok=True)
    q=p/(identifier+'.json');q.write_bytes(canonical(value));q.chmod(0o600)
    return {'grant_id':identifier,'deadline':body['deadline'],'single_native_call':True}


def authorize(settings,ledger,sid,name,args_digest,call_id,boundary):
    if not call_id or boundary not in {'execution_middleware','registry','connector_dispatch'}:raise ValueError('Trusted call identity/boundary required')
    family=ledger.lookup(sid)['session']['family'];match=None
    for p in (Path(settings['operator_dir'])/'tool-grants').glob('*.json'):
        v=read_json(p.read_bytes());b=v['body']
        if p.is_symlink() or not hmac.compare_digest(v['mac'],hmac.new(Path(settings['grant_key']).read_bytes(),canonical(b),hashlib.sha256).hexdigest()):raise ValueError('Grant authentication failed')
        if b['family']==family and b['name']==name and b['args_digest']==args_digest and b['deadline']>time.time():
            match=b;break
    if not match:raise ValueError('No exact unexpired owner grant')
    def consume(s):
        Host=ledger.__class__;Host._running(s['families'][family]);grants=s.setdefault('grants',{});old=grants.get(match['id'])
        if old:
            if old.get('state')!='tool_inflight' or old.get('call_id')!=call_id or boundary in old['boundaries']:raise ValueError('Used/revoked grant or repeated protected call')
            old['boundaries'].append(boundary)
        else:grants[match['id']]={'state':'tool_inflight','family':family,'call_id':call_id,'boundaries':[boundary]}
        return {'admitted':True,'grant_id':match['id'],'call_id':call_id}
    return ledger.mutate(consume)
