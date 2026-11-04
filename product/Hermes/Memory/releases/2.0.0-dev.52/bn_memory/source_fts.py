"""Local lexical source reserve; primary documents stay authoritative."""
import re,json
from bn_memory.store import SENSITIVE
from bn_memory import record_metadata


def install(db):
    db.execute('''CREATE TABLE IF NOT EXISTS semantic_units(
      id TEXT PRIMARY KEY,scope TEXT,kind TEXT,ref TEXT,version TEXT,meta TEXT,
      state TEXT,chars INTEGER,bytes INTEGER,total INTEGER,reason TEXT,updated REAL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS semantic_chunks(
      id TEXT PRIMARY KEY,unit TEXT,scope TEXT,begin INTEGER,end INTEGER,
      byte_begin INTEGER,byte_end INTEGER,hash TEXT,text TEXT,state TEXT,receipt TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS semantic_chunk_scope ON semantic_chunks(scope,state)')
    db.execute("CREATE VIRTUAL TABLE source_search USING fts5(id UNINDEXED,text,tokenize='unicode61')")
    db.execute('INSERT INTO source_search(id,text) SELECT id,text FROM semantic_chunks')
    for name,event,body in [
        ('insert','INSERT','INSERT INTO source_search(id,text) VALUES(new.id,new.text);'),
        ('delete','DELETE','DELETE FROM source_search WHERE id=old.id;'),
        ('update','UPDATE','DELETE FROM source_search WHERE id=old.id; INSERT INTO source_search(id,text) VALUES(new.id,new.text);')]:
        db.execute('CREATE TRIGGER source_search_'+name+' AFTER '+event+' ON semantic_chunks BEGIN '+body+' END')
    db.execute("INSERT INTO meta VALUES('source_fts_contract','1')")


def expression(query):
    if not isinstance(query,str) or len(query)>1024 or SENSITIVE.search(query):raise ValueError('query_invalid')
    tokens=re.findall(r'\w+',query,re.UNICODE)[:24]
    return ' OR '.join('"'+token+'"' for token in tokens)


def search(index,sid,query,limit=5,offset=0):
    if type(limit) is not int or not 1<=limit<=10 or type(offset) is not int or offset<0:raise ValueError('page_invalid')
    expr=expression(query)
    empty={'records':[],'source_fragments':[],'ranked_results':[],'derived':{},'has_more':False,'next_offset':None,
           'retrieval_completeness':'ranked_candidates_only','reading_credit':False,'evidence_status':'unreviewed',
           'backend':'sqlite_fts5_records_and_sources','scope':index.scopes(sid)}
    if not expr:return empty
    store=index.store;binding=store.binding(sid);scopes=index.scopes(sid)
    placeholders=','.join('?' for _ in scopes)
    with store.db() as db:
        from bn_memory.source_visibility import Visibility
        db.create_function('bn_dependencies_visible',1,lambda raw:Visibility(store).visible(db,binding,raw))
        def visible(identifier):
            try:index.read(sid,identifier,lexical=True);return 1
            except (PermissionError,ValueError,KeyError,FileNotFoundError,RuntimeError):return 0
        db.create_function('bn_source_visible',1,visible)
        role_sql,role_args=record_metadata.search_filter(binding)
        role_sql+=' AND bn_dependencies_visible(m.attributes)=1'
        source_filter='';source_args=[]
        if binding['readonly'] and store.config.get('w3_enabled'):
            from bn_memory.assignment_resources import read
            documents=read(store,binding)['documents']
            source_filter=" AND c.unit IN (SELECT id FROM semantic_units WHERE kind='document' AND json_extract(meta,'$.doc_id') IN (SELECT value FROM json_each(?)))"
            source_args=[json.dumps(list(documents))]
        sql=f'''WITH
          memory_matches AS MATERIALIZED (
            SELECT r.id,bm25(search) AS score FROM search
            JOIN records r ON r.id=search.id JOIN current u ON u.id=r.id AND u.revision=r.revision
            JOIN record_metadata m ON m.id=r.id AND m.revision=r.revision
            WHERE search MATCH ? AND r.status='recorded' AND r.scope IN ({placeholders}) {role_sql}),
          source_matches AS MATERIALIZED (
            SELECT c.id,bm25(source_search) AS score FROM source_search
            JOIN semantic_chunks c ON c.id=source_search.id
            WHERE source_search MATCH ? AND c.scope IN ({placeholders}) {source_filter} AND bn_source_visible(c.id)=1),
          ranked AS (
            SELECT id,'memory' AS kind,ROW_NUMBER() OVER(ORDER BY score,id) AS ordinal FROM memory_matches
            UNION ALL
            SELECT id,'source',ROW_NUMBER() OVER(ORDER BY score,id) FROM source_matches)
          SELECT id,kind,ordinal FROM ranked ORDER BY ordinal,id LIMIT ? OFFSET ?'''
        refs=db.execute(sql,[expr,*scopes,*role_args,expr,*scopes,*source_args,limit+1,offset]).fetchall()
    records=[];sources=[];ranks=[]
    for ref in refs[:limit]:
        # A change after ranking fails this result, rather than falsely claiming a current page.
        row=index.read(sid,ref['id'],lexical=True) if ref['kind']=='source' else store.read(sid,ref['id'])
        (sources if ref['kind']=='source' else records).append(row)
        ranks.append({'id':ref['id'],'kind':ref['kind'],'fusion_score':1/(60+ref['ordinal'])})
    return {**empty,'records':records,'source_fragments':sources,'ranked_results':ranks,
            'has_more':len(refs)>limit,'next_offset':offset+limit if len(refs)>limit else None,
            'ranking':'reciprocal_lexical_rank; correlated indexes are not independent evidence'}
