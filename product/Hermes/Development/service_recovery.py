"""Trusted local operator review, never a model-exposed source of retry authority."""
import hashlib,json,sqlite3,time,sys
from pathlib import Path
from service_auth import ROOT
def command(argv):
 cfg=json.loads((ROOT/'Memory/settings.json').read_text());sys.path.insert(0,cfg['package_root']);profile=cfg['namespace']['profile_id'];database=Path(cfg['state_root'])/'memory.sqlite'
 if not database.is_file():raise PermissionError('initialized_owner_database_required')
 db=sqlite3.connect(database);db.row_factory=sqlite3.Row
 try:
  if argv==['pending']:
   if not db.execute("SELECT 1 FROM sqlite_master WHERE name='service_results'").fetchone():return {'service_journal_present':False,'pending':[],'service_execution_implied':False}
   return {'operator_boundary_not_human_authentication':True,'pending':[{'result_id':r['result_id'],'session':r['sid'],'request_id':r['request_id'],'basis':r['basis']} for r in db.execute("SELECT * FROM service_results WHERE profile_id=? AND state='outcome_unknown' ORDER BY rowid",(profile,))]}
  if len(argv)!=3 or argv[0]!='reconcile-not-performed':raise ValueError('pending | reconcile-not-performed RESULT_ID EVIDENCE_JSON')
  rid=argv[1];original_path=Path(argv[2]).absolute()
  if any(p.is_symlink() for p in [original_path,*original_path.parents]):raise PermissionError('review_evidence_links_forbidden')
  path=original_path.resolve();root=(ROOT/'workspace').resolve()
  if not path.is_relative_to(root) or path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=1048576:raise PermissionError('regular_nonsecret_project_review_receipt_required')
  raw=path.read_bytes();e=json.loads(raw)
  if e.get('outcome')!='not_performed' or e.get('native_executor_checked') is not True or e.get('external_effects_checked') is not True or len(e.get('verification',''))<20:raise PermissionError('explicit_checked_not_performed_evidence_required_no_inference_from_error')
  from bn_memory.action_review import evidence_bytes
  digest=hashlib.sha256(raw).hexdigest();evidence_bytes(path,digest)
  db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT * FROM service_results WHERE profile_id=? AND result_id=? AND state='outcome_unknown'",(profile,rid)).fetchone()
  if row is None or e.get('result_id')!=rid or e.get('basis')!=row['basis']:raise PermissionError('exact_unsettled_operation_and_evidence_fingerprint_required')
  original=json.dumps(dict(row),ensure_ascii=False,sort_keys=True,separators=(',',':'))
  db.execute('CREATE TABLE IF NOT EXISTS service_reconciliations(profile_id TEXT,result_id TEXT,revision INTEGER,original TEXT,original_sha256 TEXT,evidence BLOB,evidence_sha256 TEXT,created REAL,PRIMARY KEY(profile_id,result_id,revision))')
  revision=db.execute('SELECT coalesce(max(revision),0)+1 FROM service_reconciliations WHERE profile_id=? AND result_id=?',(profile,rid)).fetchone()[0]
  db.execute('INSERT INTO service_reconciliations(profile_id,result_id,revision,original,original_sha256,evidence,evidence_sha256,created) VALUES(?,?,?,?,?,?,?,?)',(profile,rid,revision,original,hashlib.sha256(original.encode()).hexdigest(),raw,digest,time.time()))
  db.execute("UPDATE service_results SET state='reviewed_not_performed' WHERE profile_id=? AND result_id=? AND state='outcome_unknown'",(profile,rid));db.commit()
  return {'reviewed':True,'outcome':'not_performed','conclusion_status':'operator_attested_not_automatic_proof','original_attempt_and_evidence_preserved':True,'new_operation_performed':False,'next':'Only after this review may the same operation use a new request_id. Do not reuse the archived request_id.'}
 finally:db.close()
