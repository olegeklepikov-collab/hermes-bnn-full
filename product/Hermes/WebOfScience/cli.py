import argparse,json,sys,re
from pathlib import Path
from api import P,OPERATIONS,call,load,save
p=argparse.ArgumentParser(prog='wos-bn');p.add_argument('command',choices=['status','catalog','profiles','call']);p.add_argument('--name');p.add_argument('--profile');p.add_argument('--params',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
try:
 profiles=load(P/'config/profiles.json');params=load(a.params) if a.params else {}
 if a.profile:
  preset=profiles[a.profile];a.name=preset['name'];params={**preset.get('arguments',{}),**params}
  for key,template in preset.get('template',{}).items():
   if key not in params:
    fields=re.findall(r'\{(\w+)\}',template);values={k:params.pop(k) for k in fields};params[key]=template.format(**values)
 result=OPERATIONS if a.command=='catalog' else profiles if a.command=='profiles' else call('service_status',{}) if a.command=='status' else call(a.name,params)
 if a.output:save(a.output,result);print(a.output)
 else:print(json.dumps(result,ensure_ascii=False,indent=2))
 if result.get('ok') is False:sys.exit(2)
except Exception as e:print(json.dumps({'ok':False,'error_type':type(e).__name__},ensure_ascii=False),file=sys.stderr);sys.exit(2)
