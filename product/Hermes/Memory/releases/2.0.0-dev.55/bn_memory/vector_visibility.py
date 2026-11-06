"""Exact version allow-list for native vector pre-filtering. No model-supplied predicates."""
import math
import re


def allowlist(value,scopes):
    if not isinstance(value,list):raise ValueError('vector_record_allowlist_required')
    result=[];seen=set()
    for row in value:
        if not isinstance(row,dict) or set(row)!={'id','revision','content_hash','scope'}:raise ValueError('vector_candidate_contract_invalid')
        if (not isinstance(row['id'],str) or not re.fullmatch('MEM-[a-f0-9]{24}',row['id'])
                or type(row['revision']) is not int or row['revision']<1
                or not isinstance(row['content_hash'],str) or not re.fullmatch('[a-f0-9]{64}',row['content_hash'])
                or row['scope'] not in scopes or row['id'] in seen):
            raise ValueError('vector_candidate_contract_invalid')
        seen.add(row['id']);result.append(dict(row))
    return result


def predicates(rows,batch_size=128):
    """Split the admitted set, never the mandatory predicate or the final result."""
    if type(batch_size) is not int or not 1<=batch_size<=128:raise ValueError('vector_filter_batch_invalid')
    for start in range(0,len(rows),batch_size):
        batch=rows[start:start+batch_size]
        yield ' OR '.join("(record_id = '"+r['id']+"' AND revision = "+str(r['revision'])+" AND content_hash = '"+r['content_hash']+"')" for r in batch)


def native_contract(zv,collection):
    # The installed 0.7.0 docstring shows ==, but its native parser accepts SQL =.
    # The exact expression is exercised against the actual native library.
    if zv.__version__!='0.7.0':raise RuntimeError('vector_prefilter_runtime_not_qualified')
    schema=collection.schema.vector('embedding')
    if schema.dimension!=1024 or schema.data_type!=zv.DataType.VECTOR_FP32 or schema.index_param.metric_type!=zv.MetricType.IP:
        raise RuntimeError('vector_prefilter_schema_not_qualified')


def ranked(rows,limit):
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('vector_topk_invalid')
    if any(type(r.get('score')) not in {int,float} or not math.isfinite(r['score']) for r in rows):raise ValueError('vector_score_invalid')
    return sorted(rows,key=lambda r:(-r['score'],r['id']))[:limit]
