"""Operator entry point for the same deterministic parser executor used by BN and UDR."""
import argparse,json
from pathlib import Path
from bn_memory.parser_host import run_step
from bn_memory.documents import FORMATS
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--python',required=True);p.add_argument('--format');p.add_argument('--step-units',type=int,default=64);p.add_argument('--step-seconds',type=int,default=45);p.add_argument('--xls-java');a=p.parse_args()
fmt=a.format or FORMATS.get(a.input.suffix.lower())
if not fmt:raise SystemExit('Unsupported format; no claim of successful parsing')
r=run_step({'path':str(a.input),'output':str(a.output),'format':fmt,'xls_java':a.xls_java},a.python,{'max_units':a.step_units,'step_seconds':a.step_seconds})
print(json.dumps(r,ensure_ascii=False,indent=2))
raise SystemExit(2 if r['status']=='blocked' else 0)
