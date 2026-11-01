#!/usr/bin/env python3
"""Launch only the installed local R adapter under the same mandatory OS sandbox."""
from pathlib import Path
import argparse,json,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bn_gsd.sandbox import profile,environment
p=argparse.ArgumentParser();p.add_argument('--settings',required=True);a=p.parse_args();settings=json.loads(Path(a.settings).read_text())
from hermes_constants import get_hermes_home
root=Path(settings['runtime_root']); command=Path(settings.get('r_native_home',str(Path(settings['r_runtime'])/'env/lib/R')))/'bin/Rscript'
os.chdir(settings['workspace'])
os.execve('/usr/bin/sandbox-exec',['sandbox-exec','-p',profile(settings),str(command),'--vanilla',str(root/'R/scripts/server.R')],environment(settings))
