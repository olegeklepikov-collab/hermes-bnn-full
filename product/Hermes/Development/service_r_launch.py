"""R temp path relative to its confined working directory; no outside alias."""
import os,resource,sys
directory=os.path.join(os.environ['HERMES_BN_R_HOME'],'projects','default')
os.makedirs(os.path.join(directory,'.tmp'),exist_ok=True)
os.chdir(directory)
os.environ['TMPDIR']='.tmp'
os.environ['R_TMPDIR']=os.environ['TMPDIR']
# Do not impose a cumulative CPU allowance on a persistent research session.
# The host supervises each invocation and terminates only its own timed-out peer.
resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024*1024,128*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
program='/Library/Frameworks/R.framework/Resources/bin/exec/R'
os.execve(program,[program,*sys.argv[1:]],os.environ)
