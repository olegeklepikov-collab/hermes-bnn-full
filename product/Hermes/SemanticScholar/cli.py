import argparse,json,sys
from pathlib import Path
from api import OPERATIONS,call,status
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(prog='semantic-scholar-bn');p.add_argument('command',choices=['catalog','status','profiles','call']);p.add_argument('--name');p.add_argument('--profile');p.add_argument('--params',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
try:
 profiles=json.loads((ROOT/'config/profiles.json').read_text()) if (ROOT/'config/profiles.json').exists() else {}
 params=json.loads(a.params.read_text()) if a.params else {}
 if a.profile:
  preset=profiles[a.profile];a.name=preset['name'];params={**preset.get('arguments',{}),**params}
 result=OPERATIONS if a.command=='catalog' else status() if a.command=='status' else profiles if a.command=='profiles' else call(a.name,params)
 text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text);a.output.chmod(0o600);print(str(a.output))
 else:print(text,end='')
 if result.get('ok') is False:sys.exit(2)
except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
