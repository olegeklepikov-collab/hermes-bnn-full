"""Validated versioned vectors; legacy vectors remain untouched and unpromoted."""
import json,time
from bn_memory.store import canonical,sha,SENSITIVE
from bn_memory.embedding_contract import cache_contract,vector


class Cache:
    def __init__(self,store,config,purpose):
        self.store=store;self.contract=cache_contract(store,config,purpose)
    def key(self,text):
        if not isinstance(text,str) or not text.strip() or SENSITIVE.search(text):raise ValueError('secret_or_empty_not_embedding')
        if len(text.encode())>96000:raise ValueError('split_embedding_text_with_addresses_required')
        return sha(canonical([self.contract['contract_hash'],sha(text)]))
    def get(self,text):
        key=self.key(text)
        with self.store.db() as db:
            marker=db.execute("SELECT value FROM meta WHERE key='embedding_contract'").fetchone()
            if not marker or marker[0]!='2':raise RuntimeError('explicit_embedding_contract_migration_required')
            row=db.execute('SELECT * FROM embedding_cache_v2 WHERE key=?',(key,)).fetchone()
        if row is None:return None
        if row['contract']!=canonical(self.contract) or row['contract_hash']!=self.contract['contract_hash'] or row['text_sha256']!=sha(text):
            raise PermissionError('embedding_cache_contract_mismatch')
        if sha(row['vector'])!=row['vector_sha256']:raise ValueError('embedding_cache_integrity_failed')
        return vector(json.loads(row['vector']))
    def put(self,db,text,value,receipt):
        raw=canonical(vector(value))
        db.execute('INSERT OR IGNORE INTO embedding_cache_v2 VALUES(?,?,?,?,?,?,?,?)',
          (self.key(text),self.contract['contract_hash'],canonical(self.contract),sha(text),raw,sha(raw),time.time(),canonical(receipt)))
