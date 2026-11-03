"""Select independent inputs before LIMIT; an unknown paid attempt is never replayed."""
from bn_memory.embedding_cache import Cache


def eligible(index,connection,scopes,limit):
    contract=Cache(index.store,index.config,'document').contract['contract_hash']
    where=' AND x.scope IN ('+','.join('?' for _ in scopes)+')' if scopes else ''
    args=list(scopes or [])
    sql='''SELECT x.* FROM semantic_chunks x WHERE x.state='pending' '''+where+'''
      AND (EXISTS(SELECT 1 FROM embedding_cache_v2 e WHERE e.contract_hash=? AND e.text_sha256=x.hash)
        OR NOT EXISTS(SELECT 1 FROM embedding_attempts a,json_each(a.input_hashes) h
          WHERE a.contract_hash=? AND a.status IN ('started_usage_unknown','outcome_or_usage_unknown') AND h.value=x.hash))
      ORDER BY x.rowid LIMIT ?'''
    return [dict(row) for row in connection.execute(sql,[*args,contract,contract,limit])]


def deferred(index,connection,scopes):
    contract=Cache(index.store,index.config,'document').contract['contract_hash']
    where=' AND x.scope IN ('+','.join('?' for _ in scopes)+')' if scopes else ''
    return connection.execute('''SELECT count(*) FROM semantic_chunks x WHERE x.state='pending' '''+where+'''
      AND NOT EXISTS(SELECT 1 FROM embedding_cache_v2 e WHERE e.contract_hash=? AND e.text_sha256=x.hash)
      AND EXISTS(SELECT 1 FROM embedding_attempts a,json_each(a.input_hashes) h
        WHERE a.contract_hash=? AND a.status IN ('started_usage_unknown','outcome_or_usage_unknown') AND h.value=x.hash)''',
        [*(scopes or []),contract,contract]).fetchone()[0]
