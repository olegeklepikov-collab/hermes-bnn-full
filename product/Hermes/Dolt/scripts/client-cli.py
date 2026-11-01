from pathlib import Path
import json,os,sys
z=Path(__file__).resolve().parents[1];env=os.environ.copy();env['DOLT_CLI_PASSWORD']=json.loads((z/'config/credentials.json').read_text())['agent_password'];env['DOLT_CLI_USER']='hermes_bn'
args=[str(z/'bin/dolt'),'--host','127.0.0.1','--port','33697','--user','hermes_bn','--use-db','knowledgework','--no-tls',*sys.argv[1:]];os.execve(args[0],args,env)
