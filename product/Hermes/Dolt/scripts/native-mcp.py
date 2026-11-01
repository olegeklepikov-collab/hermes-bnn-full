"""Launch the unchanged official MCP binary; keep lifecycle text off JSON-RPC stdout."""
from pathlib import Path
import json,os,sys,subprocess,threading,signal
z=Path(__file__).resolve().parents[1];env=os.environ.copy();env['DOLT_PASSWORD']=json.loads((z/'config/credentials.json').read_text())['agent_password']
args=[str(z/'bin/dolt-mcp-server'),'--stdio','--dolt','--host','127.0.0.1','--port','33697','--user','hermes_bn','--database','knowledgework','--log-level','warn']
p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,env=env)
def feed():
 try:
  while data:=sys.stdin.buffer.read1(65536):p.stdin.write(data);p.stdin.flush()
  p.stdin.close()
 except (BrokenPipeError,OSError):pass
def stop(sig,frame):
 if p.poll() is None:p.send_signal(sig)
for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,stop)
threading.Thread(target=feed,daemon=True).start()
for line in p.stdout:
 try:value=json.loads(line)
 except (ValueError,UnicodeDecodeError):value=None
 if isinstance(value,dict) and value.get('jsonrpc')=='2.0':sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
 else:print('[Hermes BN] Native Dolt MCP lifecycle output redirected away from JSON-RPC',file=sys.stderr,flush=True)
sys.exit(p.wait())
