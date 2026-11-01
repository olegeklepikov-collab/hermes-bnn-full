"""Pinned existing Crossref client with own public-mode cache; no copied contact or token."""
import hashlib,importlib.util,json
from pathlib import Path
from bn_memory.store import canonical,SENSITIVE

def lookup(broker,sid,args):
    broker.store.binding(sid);cfg=broker.config['public_crossref'];query=args['query']
    from bn_memory.artifacts import Artifacts
    guard=Artifacts(broker);guard.sensitive(query.encode(),guard.secrets())
    path=Path(cfg['client_file'])
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=cfg['client_sha256']:raise PermissionError('public_Crossref_client_integrity_failed')
    root=Path(broker.config['state_root'])/'public-lookups/crossref'
    spec=importlib.util.spec_from_file_location('bnn_qualified_crossref',path);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api);api.ROOT=root
    value=api.search({'query_fields':{'bibliographic':query},'rows':args.get('rows',1),'select':['DOI','title','published','URL','type','container-title']})
    value.update(provider='Crossref REST API',credential_mode='public_without_key_or_email',article_full_text_read=False)
    if value.get('email_sent'):raise PermissionError('public_lookup_unexpected_contact')
    return value
