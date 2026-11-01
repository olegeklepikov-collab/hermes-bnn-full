"""Регрессия N01–N08 и соседних границ. Только локальные искусственные данные."""
from __future__ import annotations
from pathlib import Path
from copy import deepcopy
import datetime, itertools, json, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
from triad import StrictComponent,DiagnosticComponent,validate_comparison_review,confirmation_eligible
from corpus import Corpus
from records import digest,canonical
S=StrictComponent();D=DiagnosticComponent();base=json.loads((ROOT/'examples/triad_request.json').read_text());scope=base['scope']
rows=[]
def run(name,requirement,fn):
 t=time.perf_counter()
 try:
  detail=fn();rows.append({'id':name,'requirement':requirement,'passed':True,'detail':detail,'seconds':time.perf_counter()-t})
 except Exception as e:rows.append({'id':name,'requirement':requirement,'passed':False,'error':type(e).__name__+': '+str(e),'seconds':time.perf_counter()-t})
def check(ok,message='Критерий не выполнен'):
 if not ok:raise AssertionError(message)
def reject(fn):
 try:fn()
 except (ValueError,KeyError,TypeError):return {'rejected':True}
 raise AssertionError('Недопустимый вход принят')
def cand(v=1,k='K1',withdrawn=False):
 c=deepcopy(base['candidates'][0]);c['id']=k;c['expectations']={'x':v}
 if withdrawn:c['status']='withdrawn';c['content']['withdrawal_reason']='Отвод по текущему вопросу, не опровержение';c['miss_risk']='high'
 return c
def obs(v=1,k='E1',state='observed',method=True,gen=False,group='g1'):
 return {'id':k,'key':'x','value':v,'source_id':'synthetic/event','origin_group':group,'state':state,'method_valid':method,'used_for_generation':gen}
def review(cs=None,os=None):return S.compare(cs or [cand()],os if os is not None else [obs()],scope=scope)
def diagnose(cs,os,r=None):return D.run(candidates=cs,observations=os,scope=scope,review=r if r is not None else S.compare(cs,os,scope=scope),question='Различить заданные конечные версии')
# All eligibility pairs, with exact per-ID conservation and both orders.
for i,state in enumerate(itertools.product(('observed','not_measured','invalid','unavailable'),(False,True),(False,True))):
 for j,other in enumerate(itertools.product(('observed','not_measured','invalid','unavailable'),(False,True),(False,True))):
  def pair(state=state,other=other):
   a=obs(k='E9',state=state[0],method=state[1],gen=state[2]);b=obs(k='E2',state=other[0],method=other[1],gen=other[2]);rs=[]
   for os in ([a,b],[b,a]):
    r=S.compare([cand()],os,scope=scope);check(validate_comparison_review(r,[cand()],os,scope=scope))
    row=r['rows'][0];parts=sum((row[f] for f in ('support','opposition','unknown','dependent')),[]);check(sorted(parts)==['E2','E9']);rs.append(row)
   check(rs[0]==rs[1]);want='compatible_prediction' if any(confirmation_eligible(x) for x in (a,b)) else 'underdetermined';check(rs[0]['status']==want)
   return {'row_order_invariant':True,'all_input_ids_preserved':True,'status':want}
  run(f'N01-PERM-{i}-{j}','N01',pair)
# Contract mutants: no expected result is inferred from exception text.
def mutate_test(fn):
 cs=[cand()];os=[obs()];r=review(cs,os);fn(r)
 return reject(lambda:diagnose(cs,os,r))
mutations={
 'TOP-UNKNOWN':lambda r:r.update(unregistered=True),
 'TOP-TYPE':lambda r:r.update(type='OtherReview'),
 'OLD-CONTRACT':lambda r:r.pop('comparison_contract_version'),
 'OLD-VERSION':lambda r:r.update(version=1),
 'UNKNOWN-STATUS':lambda r:r['rows'][0].update(status='arbitrary'),
 'ROW-MISSING':lambda r:r['rows'].clear(),
 'ROW-DUPLICATE':lambda r:r['rows'].append(deepcopy(r['rows'][0])),
 'ROW-EXTRA':lambda r:r['rows'][0].update(unregistered='x'),
 'MISSING-EVIDENCE':lambda r:r['rows'][0].update(support=['NOT_FOUND']),
 'OPPOSITION-ROLE':lambda r:r['rows'][0].update(opposition=['E1'],support=[]),
 'UNKNOWN-ROLE':lambda r:r['rows'][0].update(unknown=['E1'],support=[]),
 'DEPENDENT-ROLE':lambda r:r['rows'][0].update(dependent=['E1'],support=[]),
 'DUAL-ROLE':lambda r:r['rows'][0].update(unknown=['E1']),
 'DUPLICATE-ID':lambda r:r['rows'][0].update(support=['E1','E1']),
 'ERASED-SUPPORT':lambda r:r['rows'][0].update(support=[]),
 'INVENTED-SOURCE':lambda r:r['rows'][0].update(S=['no/source']),
 'M-STATUS':lambda r:r['rows'][0]['M'].update(status='underdetermined'),
 'M-TRUTH':lambda r:r['rows'][0]['M'].update(not_causal_truth=False),
 'T-RESULT':lambda r:r['rows'][0]['T'].update(actual_result='contradicted_prediction'),
 'C-SCOPE':lambda r:r['rows'][0].update(C='Other'),
 'V-EMPTY':lambda r:r['rows'][0]['J'].update(V=' '),
 'TARGET-DIGEST':lambda r:r['rows'][0].update(candidate_digest='0'*64),
 'TARGET-VERSION':lambda r:r['rows'][0].update(candidate_version=2),
 'INPUT-DIGEST':lambda r:r.update(input_digest='0'*64),
 'STRENGTH':lambda r:r['rows'][0].update(claim_strength='established_cause'),
 'RESIDUAL-MISSING':lambda r:r['residuals'].pop('risk'),
}
for key,fn in mutations.items():run('REVIEW-'+key,'N05/N06',lambda fn=fn:mutate_test(fn))
for field in ('support','opposition','unknown','dependent'):
 run('REF-'+field,'N06',lambda field=field:mutate_test(lambda r:r['rows'][0].update({field:['NOT_FOUND']})))
def active_archived():
 cs=[cand(),cand(1,'ARCHIVED',True)];r=diagnose(cs,[obs()]);check(r['compatible_in_model']==['K1']);check([x['id'] for x in r['archived_candidates']]==['ARCHIVED']);check(not r['orders']['miss_priority']);return r['identification']
run('ARCHIVE-MIXED','N04',active_archived)
def all_archived():
 cs=[cand(withdrawn=True),cand(2,'K2',True)];r=diagnose(cs,[obs()]);check(not r['compatible_in_model'] and not r['contradicted_in_model'] and not r['discriminators']);check(r['identification']=='not_established');return len(r['archived_candidates'])
run('ARCHIVE-ALL','N04',all_archived)
def reopening():
 cs=[cand(withdrawn=True)];r=review(cs,[obs()]);new=deepcopy(cs);new[0]['version']+=1;new[0]['status']='candidate';new[0]['content']['reactivation']={'previous_digest':digest(cs[0]),'reason':'Изменён вопрос','record':'synthetic/reactivation'}
 reject(lambda:diagnose(new,[obs()],r));check(diagnose(new,[obs()])['compatible_in_model']==['K1']);return {'old_review_rejected':True,'new_input_with_fresh_review_accepted':True,'history_authenticity':'external_requirement'}
run('ARCHIVE-REOPEN','N04',reopening)
for v in (True,1,1.0,[True],[1],{'a':True},{'a':1}):
 def types(v=v):
  cs=[cand(v),cand('other','K2')];r=diagnose(cs,[]);check(r['discriminators'] and r['discriminators'][0]['question_key']=='x')
 run('TYPE-'+canonical(v).decode('utf-8'),'N02',types)
def confirm():
 cs=[cand(1),cand(2,'K2')];r=diagnose(cs,[obs(gen=True)]);check(r['discriminators'][0]['kind']=='independent_confirmation');check(r['discriminators'][0]['prior_observation_ids']==['E1'])
 os=[obs(gen=True),obs(k='E2',group='new_measurement')];r2=diagnose(cs,os);check(r2['compatible_in_model']==['K1']);return {'new_observation_required_then_consumed':True}
run('CONFIRMATION','N03',confirm)
for count in (1,2,10,40):
 def ids(count=count):
  premises=[{'id':f'DERIVED.{i}','proposition':f'P{i}','source':'synthetic','status':'given'} for i in range(1,count+1)]
  rules=[{'id':f'DERIVED.{count+i}','if':'P1' if i==1 else f'Q{i-1}','then':f'Q{i}','source':'synthetic'} for i in range(1,6)]
  r=S.derive(premises,rules,scope='formal');outids=[x['id'] for x in r['facts']];check(len(outids)==len(set(outids)));check(len(r['steps'])==5)
  check(not set(x['output']['id'] for x in r['steps'])&set(x['id'] for x in premises+rules));return {'occupied_input_ids':len(premises+rules),'steps':len(r['steps'])}
 run('FORMAL-RESERVED-'+str(count),'N07',ids)
C=Corpus();modes=('G','S','D','GS','GD','SD','GSD')
for active in modes:
 for other in 'GSD':
  def members(active=active,other=other):
   fn=lambda:C.assemble_context(C.manifest(components=active,file_paths=[f'components/{other}_SYSTEM.md']),byte_limit=4_000_000)
   if other not in active:return reject(fn)
   x=fn();check(x['bytes']>0);return {'active':active,'accepted':other}
  run('MANIFEST-'+active+'-'+other,'N08',members)
for path in ('./components/S_SYSTEM.md','components/../components/S_SYSTEM.md','GSD_SYSTEM.md','S_SYSTEM.md','PROCEDURES.md','README.md'):
 run('MANIFEST-BYPASS-'+path,'N08',lambda path=path:reject(lambda:C.manifest(components='G',file_paths=[path])))
def tamper():
 m=C.manifest(components='GS');m['components']=['G'];m['digest']=digest({k:v for k,v in m.items() if k!='digest'})
 return reject(lambda:C.assemble_context(m,byte_limit=4_000_000))
run('MANIFEST-FORGED','N08',tamper)
def aliases():
 m=C.manifest(components='G',file_paths=['./COMMON.md','components/../COMMON.md']);check(len({x['path'] for x in m['files']})==len(m['files']));return C.assemble_context(m,byte_limit=4_000_000)['bytes']
run('MANIFEST-NORMALIZED','N08',aliases)
run('MANIFEST-BUDGET','N08',lambda:reject(lambda:C.assemble_context(C.manifest(components='G'),byte_limit=1)))
report={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'release':'3.0.2','test_count':len(rows),'passed_count':sum(x['passed'] for x in rows),'failed_count':sum(not x['passed'] for x in rows),'model_calls':0,'tests':rows,'scope':'Договоры исправленных конечных функций и соседние случаи; не предметная приёмка свободной LLM'}
(ROOT/'reports/remediation_tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='tests'},ensure_ascii=False,indent=2));sys.exit(bool(report['failed_count']))
