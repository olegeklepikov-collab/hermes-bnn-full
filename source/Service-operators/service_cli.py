"""Public service operator for a fresh owner; no historical test entrypoints."""
import json,sys
from service_operator import main
ALLOWED={'status','contact','setup-key','protected-keys','oauth','discover','discover-one','build','revise','contracts','plans','activate','zotero-bind','zotero-authorize','pending','reconcile-not-performed'}
if __name__=='__main__':
 if not sys.argv[1:] or sys.argv[1] not in ALLOWED:raise SystemExit('hermes-services: '+', '.join(sorted(ALLOWED)))
 print(json.dumps(main(sys.argv[1:]),ensure_ascii=False,default=str))
