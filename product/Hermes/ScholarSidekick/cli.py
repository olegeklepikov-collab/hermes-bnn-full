import argparse,asyncio,json,sys
from pathlib import Path
from api import P,load,save,mcp,rest
p=argparse.ArgumentParser(prog='scholar-sidekick-bn');p.add_argument('command',choices=['status','catalog','call','batch','profiles','rest','resource','prompt']);p.add_argument('--name');p.add_argument('--profile');p.add_argument('--params',type=Path);p.add_argument('--output',type=Path);p.add_argument('--artifact-file',type=Path);a=p.parse_args()
try:
 profiles=load(P/'config/profiles.json') if (P/'config/profiles.json').exists() else {};params=load(a.params) if a.params else {}
 if a.profile:
  v=profiles[a.profile];a.command=v.get('command','call');a.name=v['name'];params={**v.get('arguments',{}),**params}
 if a.command=='profiles':result=profiles
 elif a.command=='status':result={'mcp_url':'https://scholar-sidekick.com/api/mcp','mode':'anonymous','api_key_used':False,'selected_tools':load(P/'config/mcp-selected.json')['tools']['include'],'profiles':len(profiles),'verification':load(P/'config/verification.json') if (P/'config/verification.json').exists() else {}}
 elif a.command=='rest':result=rest(a.name,params)
 else:result=asyncio.run(mcp(a.command,a.name,params))
 if a.artifact_file:
  path=a.artifact_file.resolve();base=(P/'exports').resolve()
  if not path.is_relative_to(base):raise ValueError('Производные файлы сохраняются только в ScholarSidekick/exports.')
  content=result.get('data') if a.command=='rest' else None
  if content is None:
   for item in result.get('content',[]):
    if item.get('type')!='text':continue
    try:o=json.loads(item['text'])
    except json.JSONDecodeError:continue
    if isinstance(o,dict) and isinstance(o.get('content'),str):content=o['content'];break
  if content is None and a.command=='call' and a.name=='exportCitation' and not result.get('isError'):
   blocks=[x['text'] for x in result.get('content',[]) if x.get('type')=='text']
   if blocks:content=blocks[0]
  if not isinstance(content,str):raise ValueError('Ответ не является файлом экспорта.')
  path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_text(content);path.chmod(0o600)
  print('artifact',path)
 if a.output:save(a.output,result);print(a.output)
 else:print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
 if result.get('ok') is False or result.get('isError'):sys.exit(2)
except Exception as e:
 while isinstance(e,BaseExceptionGroup) and e.exceptions:e=e.exceptions[0]
 print(json.dumps({'ok':False,'error_type':type(e).__name__,'code':getattr(e,'code',None),'request_id':getattr(e,'request_id',None),'error':'Операция Scholar Sidekick не выполнена. Проверьте параметры, режим и ограничения сервиса.'},ensure_ascii=False),file=sys.stderr);sys.exit(2)
