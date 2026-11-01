import argparse,json,re,sys
from pathlib import Path
from api import OPERATIONS,call
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(prog='crossref-bn')
p.add_argument('command',choices=['catalog','status','profiles','call']);p.add_argument('--name');p.add_argument('--profile');p.add_argument('--params',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
try:
    profiles=json.loads((ROOT/'config/profiles.json').read_text());args=json.loads(a.params.read_text()) if a.params else {}
    if a.profile:
        preset=profiles[a.profile];a.name=preset['name'];args={**preset.get('arguments',{}),**args}
        for field in preset.get('required_inputs',[]):
            if field not in args:raise ValueError('Profile requires '+field)
        if preset.get('filter_templates'):
            fields=set(re.findall(r'\{(\w+)\}',' '.join(preset['filter_templates'])))
            values={k:args.pop(k) for k in fields}
            args['filters']=args.get('filters',[])+[t.format(**values) for t in preset['filter_templates']]
    result=OPERATIONS if a.command=='catalog' else profiles if a.command=='profiles' else call('service_status') if a.command=='status' else call(a.name,args)
    body=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x') as f:f.write(body)
        a.output.chmod(0o600);print(a.output)
    else:print(body,end='')
    if result.get('ok') is False:sys.exit(2)
except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
