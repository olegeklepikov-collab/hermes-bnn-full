from pathlib import Path
import os,sys,fcntl
for arg in sys.argv[1:]:
 if arg.startswith('-C') or any(arg==flag or arg.startswith(flag+'=') for flag in ['--db','--database','--directory','--global']):
  print('Database routing flags are disabled in the dedicated Hermes BN profile',file=sys.stderr);sys.exit(2)
z=Path(__file__).resolve().parents[1];lock=(z/'config/cli.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX);os.set_inheritable(lock.fileno(),True);os.execv(str(z/'bin/bd'),[str(z/'bin/bd'),*sys.argv[1:]])
