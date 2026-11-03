from pathlib import Path
import importlib.util,json,sqlite3,tempfile,unittest,os
p=Path(__file__).resolve().parents[2]/'packaging/bnn_telemetry.py';s=importlib.util.spec_from_file_location('telemetry',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class TelemetryTests(unittest.TestCase):
    def test_error_classification_never_exports_secret_text(self):
        text=json.dumps({'error':'[TOOL_ERROR] PermissionError: record_not_visible_to_analytical_role api_key=SYNTHETIC_PRIVATE'})
        result=m.classify(text);self.assertEqual(result[0]['category'],'analytical_visibility_denied');self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(result));self.assertEqual(m.classify(json.dumps({'data':{'error':'ordinary source text'}})),[])
        self.assertEqual(m.classify('{"ok":true,"error":null}'),[])
    def test_nested_tool_batch_preserves_bounds_not_material(self):
        raw=json.dumps([{'function':{'name':'tool_call','arguments':json.dumps({'calls':[{'name':'gsd_context','arguments':{'byte_limit':131072,'components':'GSD','profile':'High Stakes','question':'PRIVATE_MATERIAL'}}]})}}])
        value=m.calls(raw);self.assertEqual(value[0]['bounds']['byte_limit'],131072);self.assertEqual(value[0]['bounds']['profile'],'High Stakes');self.assertNotIn('PRIVATE_MATERIAL',json.dumps(value))
    def test_incomplete_is_observed_and_empty_is_not_success(self):
        self.assertEqual(m.classify('{"status":"partial"}')[0]['category'],'explicit_incomplete_outcome');self.assertEqual(m.classify('{"status":"complete"}'),[])
        self.assertEqual(m.classify('{"status":[]}'),[])
    def test_poll_reads_native_database_without_modifying_or_exporting_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp)/'root';state=Path(tmp)/'observer';(r/'Memory').mkdir(parents=True);(r/'data/logs').mkdir(parents=True);(r/'primary_state').mkdir()
            (r/'Memory/settings.json').write_text(json.dumps({'state_root':str(r/'primary_state'),'context_bytes':6000,'semantic_context':False}))
            (r/'data/gateway_state.json').write_text(json.dumps({'pid':os.getpid(),'gateway_state':'running','active_agents':1}))
            c=sqlite3.connect(r/'data/state.db');c.executescript('CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,tool_name TEXT,content TEXT,tool_calls TEXT,finish_reason TEXT,timestamp REAL);CREATE TABLE session_turn_leases(conversation_id TEXT,acquired_at REAL,expires_at REAL);');c.execute('INSERT INTO messages VALUES(1,?,?,?,?,?,?,?)',('sid','user',None,'PRIVATE_DOCUMENT',None,None,1.0));c.commit();c.close()
            c=sqlite3.connect(r/'primary_state/memory.sqlite');c.execute('CREATE TABLE context_attempts(sid TEXT,receipt TEXT)');c.execute('INSERT INTO context_attempts VALUES(?,?)',('sid',json.dumps({'request_bytes':1000000,'provider_tokens':None})));c.commit();c.close()
            before=(r/'data/state.db').read_bytes();monitor=m.Monitor(r,state);sample=monitor.poll();self.assertEqual(sample['context']['current_context_tokens'],None);self.assertEqual(before,(r/'data/state.db').read_bytes());self.assertNotIn('PRIVATE_DOCUMENT',''.join(p.read_text() for p in state.glob('*.json*')))
            monitor.poll();events=[json.loads(x) for p in state.glob('events-*') for x in p.read_text().splitlines()];self.assertEqual(len([e for e in events if e['kind']=='native_message']),1)
    def test_new_only_reports_each_failure_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);m.atom(p/'latest.json',{'observed_at_utc':'synthetic'});(p/'events-20260101.jsonl').write_text(json.dumps({'event_id':'x','kind':'native_message','failures':[{'code':'CONTEXT_LIMIT'}]})+'\n')
            self.assertEqual(len(m.report(p,True)['new_failures']),1);self.assertEqual(m.report(p,True)['new_failures'],[])
    def test_generic_persisted_refusal_is_not_a_successful_reply(self):
        self.assertEqual(m.classify('Your request was not processed. Send it again if you still want me to carry it out.')[0]['code'],'request_not_processed')
    def test_agent_only_hook_timeout_and_cross_log_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';state=Path(tmp)/'state';state.mkdir();logs=root/'data/logs';logs.mkdir(parents=True)
            callback="2026-11-02 00:00:00 WARNING hermes_cli.plugins: Hook 'pre_llm_call' callback before_turn timed out after 30s — skipping PRIVATE_INPUT\n"
            refusal='PermissionError: current_turn_context_not_ready PRIVATE_INPUT\n'
            (logs/'agent.log').write_text(callback+refusal);(logs/'errors.log').write_text(refusal)
            obj=m.Monitor.__new__(m.Monitor);obj.root=root;obj.state=state;obj.cursor={};obj.logs();obj.logs()
            events=[json.loads(line) for p in state.glob('events-*') for line in p.read_text().splitlines()]
            self.assertEqual(len(events),2);self.assertIn('pre_llm_call_callback_timeout',events[0]['codes']);self.assertIn('current_turn_context_not_ready',events[1]['codes']);self.assertNotIn('PRIVATE_INPUT',json.dumps(events))
