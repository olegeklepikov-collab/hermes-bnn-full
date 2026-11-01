from pathlib import Path
import os,plistlib,subprocess,sys,json,shlex,signal,time
r=Path('/Volumes/AgentRuntime2/active-runtime/Hermes BNN Releases/W4-20261026/Hermes-BNN-GSD-UDR-W4-neutral/Hermes');z=r/'Dolt';label='local.hermes.bn.dolt';domain='gui/'+str(os.getuid());target=domain+'/'+label;plist=z/'config'/f'{label}.plist'
action=sys.argv[1] if len(sys.argv)>1 else 'status'
if action=='install':
 command='exec /bin/bash '+shlex.quote(str(r/'bin/dolt-bn-server'))+' >> '+shlex.quote(str(z/'logs/server.log'))+' 2>> '+shlex.quote(str(z/'logs/server.error.log'))
 apple='do shell script '+json.dumps(command)
 d={'Label':label,'ProgramArguments':['/usr/bin/osascript','-e',apple],'WorkingDirectory':'/','RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null'};plist.write_bytes(plistlib.dumps(d));plist.chmod(0o600)
 # The only internal-disk file is a launchd pointer; application, environment and data reside on AgentRuntime2.
 dest=Path.home()/'Library/LaunchAgents'/plist.name;dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.is_symlink():
  if dest.resolve()!=plist.resolve():raise RuntimeError('Existing launchd pointer belongs to another installation')
 elif dest.exists():raise RuntimeError('Existing launchd file must not be overwritten')
 else:dest.symlink_to(plist)
 subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
elif action=='start':subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
elif action=='stop':
 subprocess.run(['launchctl','bootout',target],check=True)
 pidfile=z/'config/server.pid'
 if pidfile.exists():
  pid=int(pidfile.read_text());cmd=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
  if str(z/'bin/dolt') in cmd:
   os.kill(pid,signal.SIGINT)
   for _ in range(30):
    try:os.kill(pid,0)
    except ProcessLookupError:break
    time.sleep(.1)
 pidfile.unlink(missing_ok=True)
elif action=='restart':
 subprocess.run([sys.executable,__file__,'stop'],check=True)
 subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
elif action!='status':raise ValueError('Use install/start/stop/restart/status')
rp=subprocess.run(['launchctl','print',target],capture_output=True,text=True)
for line in rp.stdout.splitlines():
 if any(k in line for k in ['state =','pid =','runs =','last exit code']):print(line.strip())
print('SQL 127.0.0.1:33697')
