"""Versioned, cache-aware Voyage batches; source authority remains a caller obligation."""
import fcntl,json,time,uuid
from contextlib import ExitStack
from pathlib import Path
from bn_memory.store import canonical,sha
from bn_memory.workers import http
from bn_memory.embedding_contract import vector
from bn_memory.embedding_cache import Cache


class Embeddings:
    vector=staticmethod(vector)
    def __init__(self,store,config,request=http,authorize=None):
        self.store=store;self.config=config;self.request=request;self.authorize=authorize;self.receipt=None

    def cached(self,text,purpose):
        value=Cache(self.store,self.config,purpose).get(text)
        if value is None:raise RuntimeError('child_query_embedding_not_cached_no_remote_call')
        return value

    def many(self,texts,purpose):
        if not isinstance(texts,list) or not texts:raise ValueError('embedding_input_invalid')
        cache=Cache(self.store,self.config,purpose)
        keys={cache.key(text):text for text in texts};vectors={};hits=0;attempts=[]
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS embedding_usage(at REAL,purpose TEXT,requests INTEGER,texts INTEGER,cache_hits INTEGER,tokens INTEGER,bytes INTEGER,seconds REAL,status TEXT)')
        locks=Path(self.config['state_root'])/'embedding-locks-v2';locks.mkdir(exist_ok=True,mode=0o700)
        # Ordered per-input locks collapse duplicate paid work without serializing unrelated queries.
        with ExitStack() as stack:
            for key in sorted(keys):
                handle=stack.enter_context((locks/(key+'.lock')).open('a'))
                fcntl.flock(handle,fcntl.LOCK_EX)
            for key,text in keys.items():
                cached=cache.get(text)
                if cached is not None:vectors[key]=cached;hits+=1
            missing=[key for key in keys if key not in vectors];batches=[];batch=[];size=0
            for key in missing:
                amount=len(keys[key].encode())+256
                if batch and (len(batch)>=32 or size+amount>96000):batches.append(batch);batch=[];size=0
                batch.append(key);size+=amount
            if batch:batches.append(batch)
            for batch in batches:attempts.append(self._batch(cache,batch,keys,vectors,purpose))
            if hits:
                with self.store.db() as db:
                    db.execute('INSERT INTO embedding_usage VALUES(?,?,?,?,?,?,?,?,?)',(time.time(),purpose,0,len(keys),hits,0,0,0,'cache'))
        self.receipt={'contract':'BNEmbeddingReceiptV2','space_id':cache.contract['space_id'],
                      'contract_hash':cache.contract['contract_hash'],'purpose':purpose,'input_count':len(texts),
                      'unique_inputs':len(keys),'cache_hits':hits,'provider_requests':len(attempts),
                      'provider_reported_tokens':sum(a['tokens'] for a in attempts) if all(a['tokens'] is not None for a in attempts) else None,
                      'attempts':attempts,'authority':'vector_data_not_evidence_acceptance'}
        return [vectors[cache.key(text)] for text in texts]

    def _batch(self,cache,batch,keys,vectors,purpose):
        if self.authorize is not None:self.authorize(purpose)
        amount=sum(len(keys[key].encode())+256 for key in batch);day=time.strftime('%Y-%m-%d',time.gmtime())
        identifier='EMB-'+uuid.uuid4().hex;started=time.monotonic()
        with self.store.db() as db:
            wanted={sha(keys[key]) for key in batch}
            for old in db.execute("SELECT input_hashes FROM embedding_attempts WHERE contract_hash=? AND status IN ('started_usage_unknown','outcome_or_usage_unknown')",(cache.contract['contract_hash'],)):
                if wanted.intersection(json.loads(old[0])):raise RuntimeError('embedding_previous_outcome_unsettled_no_automatic_repeat')
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT bytes FROM budget WHERE day=?',(day,)).fetchone()
            cap=self.config.get('embedding_daily_bytes')
            if cap is not None and (row[0] if row else 0)+amount>cap:raise RuntimeError('embedding_daily_budget_exhausted')
            db.execute('INSERT INTO budget VALUES(?,?) ON CONFLICT(day) DO UPDATE SET bytes=bytes+excluded.bytes',(day,amount))
            db.execute('INSERT INTO embedding_attempts VALUES(?,?,?,?,?,?,NULL)',
                       (identifier,cache.contract['contract_hash'],purpose,canonical([sha(keys[key]) for key in batch]),'started_usage_unknown',time.time()))
        try:
            result=self.request(self.config['embedding_url'],{'model':'voyage-4-large','input':[keys[key] for key in batch],
                'output_dimension':1024,'output_dtype':'float','input_type':purpose,'truncation':False},self.config['voyage_key_file'],timeout=12)
            if result.get('model','voyage-4-large')!='voyage-4-large':raise ValueError('embedding_reported_model_mismatch')
            data=result['data']
            if not isinstance(data,list) or len(data)!=len(batch):raise ValueError('embedding_batch_mismatch')
            indexed={}
            for item in data:
                index=item['index']
                if type(index) is not int or index in indexed:raise ValueError('embedding_batch_mismatch')
                indexed[index]=vector(item['embedding'])
            if set(indexed)!=set(range(len(batch))):raise ValueError('embedding_batch_mismatch')
            tokens=result.get('usage',{}).get('total_tokens')
            if tokens is not None and (type(tokens) is not int or tokens<0):raise ValueError('embedding_usage_invalid')
            receipt={'attempt_id':identifier,'tokens':tokens,'model_reported':result.get('model'),
                     'status':'complete' if tokens is not None else 'complete_usage_unreported'}
            with self.store.db() as db:
                for index,key in enumerate(batch):cache.put(db,keys[key],indexed[index],receipt)
                db.execute('UPDATE embedding_attempts SET status=?,receipt=? WHERE id=?',(receipt['status'],canonical(receipt),identifier))
                db.execute('INSERT INTO embedding_usage VALUES(?,?,?,?,?,?,?,?,?)',(time.time(),purpose,1,len(batch),0,tokens,amount,time.monotonic()-started,receipt['status']))
            vectors.update({key:indexed[index] for index,key in enumerate(batch)})
            return receipt
        except Exception as exc:
            # A transport error does not prove that the provider charged nothing.
            with self.store.db() as db:
                db.execute('UPDATE embedding_attempts SET status=?,receipt=? WHERE id=?',('outcome_or_usage_unknown',canonical({'error_class':type(exc).__name__}),identifier))
                db.execute('INSERT INTO embedding_usage VALUES(?,?,?,?,?,?,?,?,?)',(time.time(),purpose,1,len(batch),0,None,amount,time.monotonic()-started,'outcome_or_usage_unknown'))
            raise
