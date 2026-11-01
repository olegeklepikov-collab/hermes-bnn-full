"""Конечные критерии остаточной коррекции. Не модельные опыты."""
from pathlib import Path
import sys,json,copy,itertools,datetime,hashlib
S=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
sys.dont_write_bytecode=True;sys.path.insert(0,str(S/'tools'))
from triad import GenerationComponent,execute_components,SharedBudget,HandoffChannel,residuals
from records import digest
from corpus import Corpus
B=json.loads((S/'examples/triad_request.json').read_text());g=GenerationComponent();rows=[]
def check(ok,msg='criterion_failed'):
 if not ok:raise AssertionError(msg)
def run(key,fn):
 try:detail=fn();rows.append({'id':key,'outcome':'pass','detail':detail})
 except Exception as e:rows.append({'id':key,'outcome':'fail','error':type(e).__name__+': '+str(e)})
def reject(fn):
 try:fn()
 except ValueError:return True
 raise AssertionError('invalid_input_accepted')
def cand(i,state,risk):
 x=copy.deepcopy(B['candidates'][0]);x.update(id='K'+str(i),status=state,miss_risk=risk)
 if state=='withdrawn':x['content']['withdrawal_reason']='Учебный отвод'
 return x
def req(cs,ks=None):
 q=copy.deepcopy(B['generation']);q['supplied_candidates']=cs;q['known_candidates']=ks or [];q['max_candidates']=20;q['scan_budget']=20;return q
states=list(itertools.product(('candidate','withdrawn'),('ordinary','unknown','high')))
for n,config in enumerate(itertools.product(states,repeat=3)):
 cs=[cand(i,*v) for i,v in enumerate(config)]
 def perm(cs=cs):
  active=[c for c in cs if c['status']=='candidate'];eligible=active or cs
  priority={'ordinary':0,'unknown':1,'high':2};level=max(priority[c['miss_risk']] for c in eligible)
  acceptable={c['id'] for c in eligible if priority[c['miss_risk']]==level};seen=[]
  for order in itertools.permutations(cs):
   before=copy.deepcopy(order);out=g.run(req(list(order)));field=out['candidates']+out.get('reused_candidates',[])
   check(len(field)==1 and field[0]['id'] in acceptable,'lifecycle_or_risk_lost')
   check(list(order)==list(before),'input_mutated')
   stored=field+out['archived_candidates'];check({x['id'] for x in stored}=={x['id'] for x in cs},'member_lost')
   for x in stored:check(x==next(c for c in cs if c['id']==x['id']),'member_changed')
   check(set(out['selection']['selected_ids'])==({field[0]['id']} if active else set()))
   check(set(out['structural_groups'][0]['member_bindings'])=={c['id'] for c in cs})
   seen.append(field[0]['id'])
  check(len(set(seen))==1,'representative_order_dependent');return {'permutations':6,'representative':seen[0]}
 run('GROUP-'+str(n).zfill(3),perm)
for n,(a,b) in enumerate(itertools.product(states,repeat=2)):
 def known(a=a,b=b):
  old=cand('OLD',*a);new=cand('NEW',*b);q=copy.deepcopy(B);q['generation']=req([new],[old]);q['observations']=[]
  out=execute_components('GSD',q);go=out['outputs']['G'];field=go['candidates']+go['reused_candidates']
  active=[c for c in (old,new) if c['status']=='candidate'];eligible=active or [old,new]
  level=max({'ordinary':0,'unknown':1,'high':2}[c['miss_risk']] for c in eligible)
  check(len(field)==1 and {'ordinary':0,'unknown':1,'high':2}[field[0]['miss_risk']]==level)
  check(field[0]['status']==('candidate' if active else 'withdrawn'))
  check(bool(out['outputs']['D']['orders']['miss_priority'])==bool(active and level==2),'known_obligation_not_transferred')
  return {'reused':bool(go['reused_candidates']),'active_high':bool(active and level==2)}
 run('KNOWN-'+str(n).zfill(2),known)
def fixture():
 p={'id':'PAYLOAD','version':1,'type':'CandidateSet','status':'candidate'};o={'PAYLOAD':p,'context':{'id':'CTX','version':1},'standard':{'id':'STD','version':1}}
 m={'id':'MSG','sender':'G','receiver':'S','protocol_version':'3.0','component_versions':{'G':'3.0','S':'3.0'},'corpus_digest':'c'*64,'payload_id':'PAYLOAD','payload_version':1,'payload_digest':digest(p),'dependency_bindings':{},'context_digest':digest(o['context']),'standard_digest':digest(o['standard']),'risk_floor':'eMVP','deadline':'2035-01-01T00:00:00Z','budget_reservation':'B','budget_amount':1,'allowed_effects':['local_analysis'],'residuals':residuals(),'input_status':'candidate'}
 budget=SharedBudget(100);channel=HandoffChannel(component_versions=m['component_versions'],corpus_digest=m['corpus_digest'],budget=budget);return channel,m,o,budget
badids=['',' ','x ',' x','\tx','x\n','x\x00','x\u200b','e\u0301',None,1,[],{}]
for key in ['id','payload_id','budget_reservation']:
 for i,value in enumerate(badids):
  def bad(key=key,value=value):
   ch,m,o,b=fixture();m[key]=value;reject(lambda:ch.send(m,objects=o,receiver='S'));check(not b.reservations and not ch.seen);return {'rejected_before_resource':True}
  run('HEADER-'+key+'-'+str(i),bad)
for key in ['payload_version','budget_amount']:
 for i,value in enumerate([True,1.0,'1',None,-1,[],{}]):
  def bad(key=key,value=value):
   ch,m,o,b=fixture();m[key]=value;reject(lambda:ch.send(m,objects=o,receiver='S'));check(not b.reservations);return True
  run('INTEGER-'+key+'-'+str(i),bad)
for i,value in enumerate([True,1.0,0,-1,'1',None]):
 def body(value=value):
  ch,m,o,b=fixture();o['PAYLOAD']['version']=value;m['payload_digest']=digest(o['PAYLOAD']);reject(lambda:ch.send(m,objects=o,receiver='S'));check(not b.reservations);return True
 run('BODYVERSION-'+str(i),body)
for status in ['supported','candidate','arbitrary','unreviewed']:
 def absent(status=status):
  ch,m,o,b=fixture();o['PAYLOAD'].pop('status');o['PAYLOAD']['M']='Условное содержание';m['payload_digest']=digest(o['PAYLOAD']);m['input_status']=status
  if status=='unreviewed':check(ch.send(m,objects=o,receiver='S')['state']=='accepted_for_processing')
  else:reject(lambda:ch.send(m,objects=o,receiver='S'));check(not b.reservations)
  return {'status':status,'accepted':status=='unreviewed'}
 run('UNDECLARED-STATUS-'+status,absent)
for n in range(10):
 def roundtrip(n=n):
  ch,m,o,b=fixture();m['id']='MSG'+str(n);a=ch.send(m,objects=o,receiver='S');z=ch.send(copy.deepcopy(m),objects=copy.deepcopy(o),receiver='S');check(not a['duplicate'] and z['duplicate'] and len(b.reservations)==1);return True
 run('VALID-REPLAY-'+str(n),roundtrip)
# Explicit adjacent clarification: typed constraint comparison, not numeric coercion.
values=[True,False,0,1,1.0,None,[],[True],[1],{'a':True},{'a':1},'1']
for i,a in enumerate(values):
 for j,b in enumerate(values):
  def constraint(a=a,b=b):
   q=req([]);q.pop('supplied_candidates');q.update(method='variation',product_kind='idea',axes={'x':[b]},forbidden_combinations=[{'x':a}])
   out=g.run(q)
   same=json.dumps(a,sort_keys=True,separators=(',',':'))==json.dumps(b,sort_keys=True,separators=(',',':'))
   check(bool(out['candidates']) is (not same),'constraint_comparison_inconsistent')
   return {'excluded':same}
  run(f'CONSTRAINT-{i}-{j}',constraint)
def missing_null():
 q=req([]);q.pop('supplied_candidates');q.update(method='variation',product_kind='idea',axes={'x':[1]},forbidden_combinations=[{'missing':None}])
 check(len(g.run(q)['candidates'])==1);return True
run('CONSTRAINT-ABSENT-NOT-NULL',missing_null)
report={'date':datetime.datetime.now(datetime.timezone.utc).isoformat(),'subject':str(S),'tests':len(rows),'passed':sum(r['outcome']=='pass' for r in rows),'failed':sum(r['outcome']=='fail' for r in rows),'rows':rows,'model_calls':0,'scope':'Closed local invariants; one GROUP row includes all 6 permutations; not independent field observations'}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print({k:v for k,v in report.items() if k!='rows'});raise SystemExit(bool(report['failed']))
