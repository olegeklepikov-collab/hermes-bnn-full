"""Explicit semantic space and cache reuse boundary; credentials are not cache keys."""
from urllib.parse import urlsplit
from bn_memory.store import canonical,sha


def space(config):
    endpoint=config.get('embedding_url','https://api.voyageai.com/v1/embeddings')
    parsed=urlsplit(endpoint)
    if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('embedding_endpoint_contract_invalid')
    preparation=config.get('embedding_preparation_version','exact-utf8-v1')
    if not isinstance(preparation,str) or not preparation or len(preparation)>128:raise ValueError('embedding_preparation_version_required')
    value={'contract':'BNEmbeddingSpaceV1','provider':'voyageai','endpoint':endpoint,
           'model':'voyage-4-large','dimensions':1024,'dtype':'float','preparation_version':preparation,
           'normalization':'none','truncation':False,'metric':'inner_product'}
    return {**value,'space_id':sha(canonical(value))}


def cache_contract(store,config,purpose):
    if purpose not in {'query','document'}:raise ValueError('embedding_purpose_required')
    value={**space(config),'owner_id':store.namespace['owner_id'],'profile_id':store.profile,
           'reuse_boundary':'same_owner_and_profile','purpose':purpose}
    return {**value,'contract_hash':sha(canonical(value))}


def vector(value):
    import array,math
    if not isinstance(value,list) or len(value)!=1024 or any(type(x) not in (float,int) for x in value):
        raise ValueError('embedding_vector_invalid')
    try:
        if any(not math.isfinite(x) for x in value):raise ValueError('nonfinite')
        represented=array.array('f',value)
        if any(not math.isfinite(x) for x in represented):raise ValueError('float32_overflow')
    except (ValueError,OverflowError,TypeError) as exc:raise ValueError('embedding_vector_invalid') from exc
    if not any(represented):raise ValueError('embedding_zero_vector')
    return value


def install(db):
    db.execute('''CREATE TABLE embedding_cache_v2(
        key TEXT PRIMARY KEY,contract_hash TEXT NOT NULL,contract TEXT NOT NULL,text_sha256 TEXT NOT NULL,
        vector TEXT NOT NULL,vector_sha256 TEXT NOT NULL,created REAL NOT NULL,receipt TEXT NOT NULL)''')
    db.execute('CREATE INDEX embedding_cache_contract ON embedding_cache_v2(contract_hash)')
    db.execute('''CREATE TABLE embedding_attempts(
        id TEXT PRIMARY KEY,contract_hash TEXT NOT NULL,purpose TEXT NOT NULL,
        input_hashes TEXT NOT NULL,status TEXT NOT NULL,started REAL NOT NULL,receipt TEXT)''')
    db.execute("INSERT INTO meta VALUES('embedding_contract','2')")
