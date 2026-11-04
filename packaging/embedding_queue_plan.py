"""Read-only candidate selector: quarantine unsettled inputs, keep independent work.

Integration point is SourceIndex BEFORE LIMIT. Caller still must validate source
visibility/bytes, run the existing Embeddings guard, and perform native readback.
This helper grants no provider retry and does not modify any queue or ledger.
"""
import re

def eligible(connection,contract_hash,scopes,limit=32):
    if not isinstance(contract_hash,str) or not re.fullmatch('[a-f0-9]{64}',contract_hash):raise ValueError('exact_cache_contract_required')
    if not isinstance(scopes,list) or not scopes or len(scopes)>256 or any(not isinstance(s,str) or not s for s in scopes):raise ValueError('bounded_authorized_scopes_required')
    if type(limit)is not int or not 1<=limit<=32:raise ValueError('batch_limit_invalid')
    # A same-contract cached vector can be reused without replaying a provider
    # request. Foreign-owner/purpose/space contracts do not qualify as that cache.
    sql='''SELECT x.* FROM semantic_chunks x
      WHERE x.state='pending' AND x.scope IN ('''+','.join('?' for _ in scopes)+''')
      AND (EXISTS (SELECT 1 FROM embedding_cache_v2 e
             WHERE e.contract_hash=? AND e.text_sha256=x.hash)
        OR NOT EXISTS (SELECT 1 FROM embedding_attempts a,json_each(a.input_hashes) h
             WHERE a.contract_hash=? AND a.status IN ('started_usage_unknown','outcome_or_usage_unknown')
               AND h.value=x.hash))
      ORDER BY x.rowid LIMIT ?'''
    return connection.execute(sql,(*scopes,contract_hash,contract_hash,limit)).fetchall()
