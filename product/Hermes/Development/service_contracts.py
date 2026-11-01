"""Finite meaningful service boundary checks before activation; no provider calls."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'Development/services-20261028'
CFG=json.loads((BASE/'candidate-settings.private.json').read_text());sys.path.insert(0,CFG['package_root'])
from bn_memory import service_engine as api
from bn_memory.service_delegation import permissions
from jsonschema import Draft202012Validator,ValidationError

class ServiceBoundaries(unittest.TestCase):
 def test_all_declared_method_schemas_and_effects(self):
  catalogue=api.read_catalog(CFG)
  self.assertGreater(sum(len(e['methods']) for e in catalogue['services'].values()),500)
  for sn,e in catalogue['services'].items():
   for n,m in e['methods'].items():
    with self.subTest(service=sn,method=n):
     Draft202012Validator.check_schema(m['input_schema']);self.assertEqual(m['schema_sha256'],api.sha(api.canonical(m['input_schema'])))
     self.assertIn(m['effect'],{'read','write','job','blocked'})
 def test_all_rules_unambiguous_and_effect_appropriate(self):
  from bn_memory.action_control import checked_schema
  rules=[x for x in CFG['tool_policy']['rules'] if x['id'].startswith('services.')]
  self.assertEqual(len({x['id'] for x in rules}),len(rules))
  for r in rules:
   checked_schema(r['arguments_schema'])
   if r['tool'] in {'mcp__context__service_job','mcp__context__service_write'}:self.assertEqual(r['roles'],['parent']);self.assertNotEqual(r['effect'],'query_remote')
 def test_remote_cleanup_is_available_only_as_owner_approved_mutation(self):
  cat=api.read_catalog(CFG)['services']
  for sn,name in [('scite','delete_collection'),('keenable-select','revoke_html_report'),('undermind','delete_file'),('alphaxiv','unfollow_researcher')]:
   self.assertEqual(cat[sn]['methods'][name]['effect'],'write')
   with self.assertRaises(PermissionError):api.validate_call(CFG,'read',{'service':sn,'method':name,'arguments':{}})
 def test_critical_administration_never_admitted(self):
  cat=api.read_catalog(CFG)['services']
  for service,name in [('scite','manage_subscription'),('openalex','submit_curations'),('openalex','claim_author_profile'),('firecrawl','firecrawl_feedback')]:
   self.assertEqual(cat[service]['methods'][name]['effect'],'blocked')
   with self.assertRaises(PermissionError):api.validate_call(CFG,'read',{'service':service,'method':name,'arguments':{}})
 def test_full_tavily_finance_and_advanced_options_preserved(self):
  method=api.read_catalog(CFG)['services']['tavily']['methods']['tavily_search'];schema=method['input_schema']
  self.assertIn('finance',schema['properties']['topic']['enum'])
  self.assertIn('search_depth',schema['properties']);self.assertIn('include_domains',schema['properties'])
  api.validate_call(CFG,'read',{'service':'tavily','method':'tavily_search','arguments':{'query':'official company filings','topic':'finance','search_depth':'advanced','include_domains':['sec.gov'],'max_results':2}})
 def test_exa_full_body_schema_keeps_domain_date_filters(self):
  cat=api.read_catalog(CFG)['services']['exa']['methods'];self.assertIn('api_search',cat)
  schema=cat['api_search']['input_schema'];self.assertIn('body',schema['properties'])
  text=api.canonical(schema);self.assertIn('includeDomains',text);self.assertIn('startPublishedDate',text)
 def test_delegation_exact_method_arguments_not_free_query(self):
  call={'service':'tavily','method':'tavily_search','arguments':{'query':'IANA example domains','max_results':2}}
  grant=permissions(CFG,[call]);r=next(x for x in grant if x['rule_id']=='services.tavily.tavily_search');v=Draft202012Validator(r['arguments_schema'])
  self.assertTrue(v.is_valid({**call,'request_id':'test'}))
  altered=copy.deepcopy(call);altered['arguments']['query']='different unassigned question';self.assertFalse(v.is_valid(altered))
  altered=copy.deepcopy(call);altered['service']='exa';self.assertFalse(v.is_valid(altered))
 def test_child_cannot_be_given_mutation_or_job(self):
  for service,name in [('parallel-task','createDeepResearch'),('consensus','create_thread'),('zotero','trash_item')]:
   with self.assertRaises(PermissionError):permissions(CFG,[{'service':service,'method':name,'arguments':{}}])
 def test_delegated_code_and_input_snapshots_cannot_be_cross_combined(self):
  a={'service':'rstats','method':'btw_tool_run_r','arguments':{'code':'a <- 1','_intent':'check A'},'input_files':['/fictional/A.csv']}
  b={'service':'rstats','method':'btw_tool_run_r','arguments':{'code':'b <- 2','_intent':'check B'},'input_files':['/fictional/B.csv']}
  r=next(x for x in permissions(CFG,[a,b]) if x['rule_id']=='services.rstats.btw_tool_run_r');v=Draft202012Validator(r['arguments_schema'])
  self.assertTrue(v.is_valid(a));self.assertTrue(v.is_valid(b));self.assertFalse(v.is_valid({**a,'input_files':b['input_files']}))
 def test_unknown_methods_and_host_injection_fail_before_transport(self):
  with self.assertRaises(PermissionError):api.validate_call(CFG,'read',{'service':'tavily','method':'unknown_admin','arguments':{}})
  with self.assertRaises(ValidationError):api.validate_call(CFG,'read',{'service':'tavily','method':'tavily_search','arguments':{'query':'x','endpoint':'https://other.invalid/'}})
 def test_result_unicode_crlf_pages_reconstruct_exactly(self):
  original=api.canonical({'data':'ёж\r\n'*9000});parts=[];offset=0
  while True:
   r=api.page(original,{'offset':offset,'page_chars':8192},{'result_id':'test'});parts.append(r['text'])
   self.assertEqual(r['source_sha256'],api.sha(original));self.assertFalse(r['scientific_acceptance'])
   if r['next_offset'] is None:break
   offset=r['next_offset']
  self.assertEqual(''.join(parts),original)
 def test_page_bounds_are_rejected_not_silently_clamped(self):
  for args in [{'offset':-1},{'offset':20},{'page_chars':0},{'page_chars':8193},{'offset':True}]:
   with self.assertRaises(ValueError):api.page('{}',args,{})
 def test_write_requires_exact_operator_approval_not_model_boolean(self):
  with tempfile.TemporaryDirectory() as tmp:
   key=Path(tmp)/'host.key';key.write_bytes(b'fictional-unit-test-key'*2)
   cfg={'profile_home':tmp,'host_key':str(key),'service_integration':{'approval_root':tmp}}
   with self.assertRaisesRegex(PermissionError,'exact_owner_approval'):api.approval(cfg,'s','write',{'service':'keenable-select','method':'generate_html_report','arguments':{'title':'test'},'request_id':'one','approved':True})
 def test_unsigned_broker_call_does_not_reach_transport(self):
  class Store:
   def binding(self,s):return {'profile_id':'p','sid':s}
  class Broker:store=Store()
  with self.assertRaisesRegex(PermissionError,'final_native_origin'):api.dispatch(Broker(),'s','service_read',{'service':'tavily','method':'tavily_search','arguments':{'query':'x'},'request_id':'one'})
 def test_schema_references_cannot_fetch_remote_instructions(self):
  evil={'services':{'fake':{'methods':{'tool':{'effect':'read','input_schema':{'$ref':'https://not-allowed.invalid/schema'}}}}}}
  with patch.object(api,'read_catalog',return_value=evil):
   with self.assertRaises(Exception):api.validate_call({},'read',{'service':'fake','method':'tool','arguments':{}})
 def test_all_required_controls_retained(self):
  current=json.loads((ROOT/'data/execution-controls.json').read_text());self.assertEqual(set(current['required']),{'tool','tool_result','llm','auxiliary','subagent_launch'})
  self.assertTrue(all(x==['bn-common-memory'] for x in current['required'].values()))
 def test_literal_schema_data_can_be_delegated_without_allowing_executable_refs(self):
  from bn_memory.action_control import checked_schema
  literal={'body':{'schema':{'$ref':'#/$defs/row','$defs':{'row':{'type':'string'}}}}}
  validator=checked_schema({'type':'object','properties':{'arguments':{'const':literal}},'required':['arguments']})
  self.assertTrue(validator.is_valid({'arguments':literal}));self.assertFalse(validator.is_valid({'arguments':{}}))
  for value in [{'$ref':'https://external.invalid/schema'},{'allOf':[{'$ref':'#/other'}]}]:
   with self.assertRaises(ValueError):checked_schema(value)
 def test_every_declared_rest_endpoint_is_a_pinned_official_host(self):
  from urllib.parse import urlsplit
  allowed={'api.firecrawl.dev','api.exa.ai','api.tavily.com','sdk.nimbleway.com','api.parallel.ai','api.keenable.ai','api.datacite.org','agent.tinyfish.ai','api.search.tinyfish.ai','api.fetch.tinyfish.ai','api.browser.tinyfish.ai','elicit.com','repo-prod.prod.sagebase.org'}
  for sn,e in api.read_catalog(CFG)['services'].items():
   for n,m in e['methods'].items():
    if m.get('api_request'):
     req=m['api_request'];p=urlsplit(req['base']);self.assertEqual(p.scheme,'https');self.assertIn(p.hostname,allowed);self.assertTrue(req['path'].startswith('/'))
 def test_each_included_program_is_unchanged_since_candidate_build(self):
  reg=json.loads(Path(CFG['service_integration']['registry_file']).read_text())
  for e in reg['services']:
   if e['service'] not in {'beads','dolt','beads-dolt'} and not e.get('reauthorization_required'):
    try:api.verify_entry(CFG,e['service'])
    except PermissionError as exc:self.assertEqual(str(exc),'service_connection_not_ready: '+e['connection_hold'] if e.get('connection_hold') else 'service_oauth_expired_independent_login_required')
 def test_real_sql_journal_and_renamed_search_reuse(self):
  import sqlite3,contextlib
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   authority=Path(tmp)/'authority.json';authority.write_text('{"headers":{},"env":{}}')
   class Store:
    profile='main'
    def binding(self,sid):return {'profile_id':'main','sid':sid,'project':'p','readonly':False,'parent':None}
    @contextlib.contextmanager
    def db(self):
     c=sqlite3.connect(Path(tmp)/'journal.sqlite');c.row_factory=sqlite3.Row
     try:yield c;c.commit()
     finally:c.close()
   class Guard:
    def __init__(self,*args):pass
    def secrets(self):return []
    def sensitive(self,*args):pass
   class Visibility:
    def __init__(self,*args):pass
    def source(self,*args):pass
    def closure(self,*args,**kwargs):pass
   class Pool:
    calls=0
    def request(self,*args):
     self.calls+=1
     if getattr(self,'fail',False):raise TimeoutError('synthetic unknown outcome')
     return {'isError':False,'data':{'title':'Synthetic journal fixture'}}
   broker=SimpleNamespace(config=CFG,store=Store())
   request={'service':'tavily','method':'tavily_search','arguments':{'query':'journal fixture'},'request_id':'one'}
   with patch('bn_memory.write_origin.for_binding',return_value={'attempt_id':'native-fixture','step_id':'same-native-step'}),patch.object(api,'verify_entry',return_value={'service':'tavily','transport':'http','authority_file':str(authority)}),patch('bn_memory.artifacts.Artifacts',Guard),patch('bn_memory.source_visibility.Visibility',Visibility),patch('bn_memory.service_pool.Pool',Pool):
    first=api.dispatch(broker,'test-parent','service_read',request)
    same=api.dispatch(broker,'test-parent','service_read',request)
    renamed=api.dispatch(broker,'test-parent','service_read',{**request,'request_id':'two'})
    self.assertEqual(broker._service_pool.calls,1);self.assertEqual(first['new_provider_calls'],1);self.assertEqual(same['new_provider_calls'],0);self.assertEqual(renamed['new_provider_calls'],0)
    self.assertTrue(renamed['same_step_identical_search_reused']);self.assertEqual(first['source_sha256'],renamed['source_sha256'])
    with self.assertRaisesRegex(PermissionError,'request_id_conflict'):api.dispatch(broker,'test-parent','service_read',{**request,'arguments':{'query':'changed fixture'}})
    with self.assertRaisesRegex(PermissionError,'outside_assignment'):api.dispatch(broker,'other-session','service_result',{'result_id':first['result_id']})
    broker._service_pool.fail=True
    uncertain={**request,'request_id':'uncertain','arguments':{'query':'uncertain fixture'}}
    with self.assertRaises(TimeoutError):api.dispatch(broker,'test-parent','service_read',uncertain)
    with patch('bn_memory.write_origin.for_binding',return_value={'attempt_id':'later-attempt','step_id':'later-native-step'}):
     with self.assertRaisesRegex(PermissionError,'equivalent_service_outcome_unknown'):api.dispatch(broker,'test-parent','service_read',{**uncertain,'request_id':'renamed-next-turn'})
    self.assertEqual(broker._service_pool.calls,2)
    with broker.store.db() as db:self.assertEqual(db.execute("SELECT state FROM service_results WHERE request_id='uncertain'").fetchone()[0],'outcome_unknown')
 def test_produced_result_policy_only_grants_producer_and_preserves_explicit_restrictions(self):
  import contextlib
  changes=[]
  class Store:
   @contextlib.contextmanager
   def db(self):yield object()
  class Visibility:
   revision=0
   def __init__(self,store):pass
   def policy(self,*args):return {},self.revision
   def revise(self,*args,**kwargs):changes.append((args,kwargs))
  with patch('bn_memory.source_visibility.Visibility',Visibility):
   api.register_produced_source(Store(),{'readonly':True,'role':'computation'},'new bytes',{'input_snapshots':[{'sha256':'a'*64}]})
   Visibility.revision=1
   api.register_produced_source(Store(),{'readonly':True,'role':'G'},'new bytes',{})
  self.assertEqual(len(changes),1);self.assertEqual(changes[0][0][2]['allowed_roles'],['parent','computation']);self.assertEqual(changes[0][1]['source_dependencies'],[{'kind':'source','sha256':'a'*64}])
 def test_new_service_result_scope_is_exact_and_does_not_edit_assignment(self):
  from types import SimpleNamespace
  binding={'readonly':True,'_assigned_sources':['a'*64],'_assigned_records':{},'role':'collector'}
  captured=[]
  class Visibility:
   def __init__(self,store):pass
   def closure(self,db,scoped,items,track):captured.append((scoped,items))
  with patch('bn_memory.source_visibility.Visibility',Visibility):api.visible_body(None,binding,'synthetic result',{'input_snapshots':[{'sha256':'a'*64}]},db=object())
  self.assertEqual(binding['_assigned_sources'],['a'*64])
  scoped,items=captured[0];self.assertEqual(set(scoped['_assigned_sources']),{'a'*64,api.sha('synthetic result')});self.assertEqual(scoped['role'],'collector');self.assertIn({'kind':'source','sha256':'a'*64},items)
 def test_streamed_rest_response_parses_captured_bytes_not_consumed_stream(self):
  from bn_memory.service_transport import rest_call
  class Response:
   status_code=200;headers={'content-type':'application/json'}
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def iter_content(self,*args):yield b'{"results":[{"title":"Synthetic fixture"}]}'
   def json(self):raise RuntimeError('The content for this response was already consumed')
  class Client:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def request(self,*args,**kwargs):return Response()
  with patch('requests.Session',Client):
   result=rest_call({'service':'exa'},{'api_request':{'method':'POST','base':'https://api.exa.ai','path':'/search','parameters':{}}},{'body':{'query':'fixture'}},{'headers':{'x-api-key':'fictional_unit_test_key'}})
  self.assertEqual(result['data']['results'][0]['title'],'Synthetic fixture');self.assertFalse(result['isError'])
 def test_public_docs_placeholders_do_not_disable_actual_secret_blocking(self):
  class Guard:
   def sensitive(self,data,values):
    from bn_memory.store import SENSITIVE
    if any(v in data for v in values) or SENSITIVE.search(data.decode()):raise PermissionError('fixture_guard')
  guard=Guard();secret=b'fictional-real-key-0123456789'
  api.incoming_result(guard,'Example api_key=YOUR_API_KEY',[secret],'nimble-docs')
  api.incoming_result(guard,'API_KEY:=}`), and Bearer YOUR_OMNIROUTE_KEY',[secret],'nimble-docs')
  with self.assertRaises(PermissionError):api.incoming_result(guard,'api_key='+secret.decode(),[secret],'nimble-docs')
  with self.assertRaises(PermissionError):api.incoming_result(guard,'api_key=unrecognized_very_long_value',[],'nimble-docs')

def run():
 tests=unittest.defaultTestLoader.loadTestsFromTestCase(ServiceBoundaries)
 if (ROOT/'Development/service_extension_contracts.py').exists():
  from service_extension_contracts import suite
  tests.addTests(suite(CFG,api))
 result=unittest.TextTestRunner(verbosity=2).run(tests)
 out={'ok':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'new_provider_calls':0,'model_calls':0,'candidate_manifest_sha256':hashlib.sha256((Path(CFG['package_root'])/'manifest.json').read_bytes()).hexdigest()}
 (BASE/'contracts-status.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');return out
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
