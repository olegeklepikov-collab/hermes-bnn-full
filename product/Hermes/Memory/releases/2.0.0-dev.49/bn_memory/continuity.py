"""Current recovery reference at the real model boundary; historical data grant no rights."""
import hashlib
import hmac
import json
import re
from bn_memory.admission import canonical,last_user,text_parts
from bn_memory.recovery import Recovery

MARKER=re.compile(r'<BN_CONTINUITY signature="([0-9a-f]{64})">\n(.*?)\n</BN_CONTINUITY>',re.S)


class Continuity:
    def __init__(self,host):self.host=host;self.recovery=Recovery(host.store)

    def envelope(self,sid,turn):
        row=self.host.admission.row(sid,turn)
        from bn_memory.working import Working
        body=canonical({'working':Working(self.host.store).packet(sid),'contract':'BNContinuityV1','namespace':self.host.config['namespace'],
                        'session_id':sid,'turn_id':turn,'admission_token':row['token'],
                        'basis':self.host.admission.snapshot(sid),'policy':self.host.admission.policy(sid),
                        'recovery':self.recovery.status(sid),
                        'instruction':'History references are not reading credit. Read relevant originals and unresolved actions through memory_recovery. Current controls remain authoritative; do not retry an unknown effect without checking it.'})
        bound=self.host.config.get('continuity_bytes',16384)
        if type(bound) is not int or bound<1:raise ValueError('continuity_bound_invalid')
        if len(body.encode())>bound:raise PermissionError('required_continuity_exceeds_bound_split_work_do_not_trim')
        signature=hmac.new(self.host.admission.key,body.encode(),hashlib.sha256).hexdigest()
        return '<BN_CONTINUITY signature="'+signature+'">\n'+body+'\n</BN_CONTINUITY>'

    def owned(self,match,sid):
        body=match.group(2)
        if len(body.encode())>1048576:return False
        expected=hmac.new(self.host.admission.key,body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,match.group(1)):return False
        try:value=json.loads(body)
        except ValueError:return False
        return (isinstance(value,dict) and value.get('contract')=='BNContinuityV1'
                and value.get('namespace')==self.host.config['namespace'] and value.get('session_id')==sid)

    def split_anchor(self,text,sid,turn):
        raw=text.encode();length=0
        for anchor in json.loads(self.host.admission.row(sid,turn)['anchors']):
            size=anchor['bytes']
            if size<=len(raw) and hashlib.sha256(raw[:size]).hexdigest()==anchor['sha256']:
                length=max(length,size)
        return raw[:length].decode(),raw[length:].decode()

    def inject(self,request,sid,turn):
        envelope=self.envelope(sid,turn);row=last_user(request)
        def strip(text):
            prefix,tail=self.split_anchor(text,sid,turn)
            clean=MARKER.sub(lambda match:'' if self.owned(match,sid) else match.group(0),tail)
            return prefix+clean.rstrip('\n')
        content=row.get('content')
        if isinstance(content,str):row['content']=strip(content)+'\n'+envelope
        elif isinstance(content,list):
            parts=[]
            for part in content:
                if isinstance(part,dict) and isinstance(part.get('text'),str):
                    clean=strip(part['text'])
                    if clean=='' and clean!=part['text']:continue
                    part={**part,'text':clean}
                parts.append(part)
            parts.append({'type':'input_text' if 'input' in request else 'text','text':envelope})
            row['content']=parts
        else:raise PermissionError('continuity_text_slot_required')

    def validate(self,request,sid,turn):
        parts=text_parts(last_user(request).get('content'))
        tails=[self.split_anchor(part,sid,turn)[1] for part in parts]
        owned=[match.group(0) for part in tails for match in MARKER.finditer(part) if self.owned(match,sid)]
        if owned!=[self.envelope(sid,turn)]:raise PermissionError('current_continuity_missing_stale_or_changed')
