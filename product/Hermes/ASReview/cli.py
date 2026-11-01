import argparse,json,sys
from pathlib import Path
from api import ROOT,OPS,call
p=argparse.ArgumentParser();p.add_argument('command',choices=['status','catalog','profiles','call']);p.add_argument('--name');p.add_argument('--params',type=Path);p.add_argument('--profile');p.add_argument('--output',type=Path);a=p.parse_args();args=json.loads(a.params.read_text()) if a.params else {}
if a.command=='catalog':res={n:{k:v for k,v in d.items() if k!='fn'} for n,d in OPS.items()}
elif a.command=='profiles':res=json.loads((ROOT/'config/profiles.json').read_text())
else:
 if a.profile:
  cfg=json.loads((ROOT/'config/profiles.json').read_text())[a.profile];a.name=cfg['name'];args={**cfg['arguments'],**args}
 res=call('service_status' if a.command=='status' else a.name,args)
s=json.dumps(res,ensure_ascii=False,indent=2)+'\n'
if a.output:
 with a.output.open('x') as f:f.write(s)
 a.output.chmod(0o600);print(a.output)
else:print(s,end='')
if res.get('ok') is False:sys.exit(2)
