"""Official Pendar MCP using this Hermes BN instance's independent OAuth."""
import argparse, asyncio, json, sys
from pathlib import Path
P=Path(__file__).resolve().parent; R=P.parent
sys.path.insert(0,str(R/'hermes-agent'))
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()
ALLOWED={'verify_paper','survey_literature','graph_hopper','audit_bibliography','profile_researcher','find_venues'}

async def run(command,name,params):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from jsonschema import Draft202012Validator
    from tools.mcp_tool_config import _load_mcp_config
    from tools.mcp_oauth_manager import get_manager
    import httpx2
    cfg=_load_mcp_config().get('pendar')
    if not cfg or cfg.get('url')!='https://pendar.ai/mcp' or cfg.get('auth')!='oauth' or not cfg.get('enabled',True):
        raise ValueError('Нужно отдельное подключение Pendar в Hermes BN.')
    auth=get_manager().get_or_build_provider('pendar',cfg['url'],cfg.get('oauth'))
    if auth is None:raise ValueError('Вход Pendar ещё не завершён; повторный запрос ключа не требуется.')
    async with httpx2.AsyncClient(auth=auth,timeout=180) as http:
      async with streamable_http_client(cfg['url'],http_client=http) as streams:
       async with ClientSession(streams[0],streams[1],read_timeout_seconds=180) as s:
        init=await s.initialize(); listing=await s.list_tools();catalog={t.name:t for t in listing.tools}
        if command=='catalog':
            await s.send_ping()
            prompts=await s.list_prompts() if init.capabilities.prompts else None
            resources=await s.list_resources() if init.capabilities.resources else None
            return {'initialize':init.model_dump(mode='json',by_alias=True),'tools':listing.model_dump(mode='json',by_alias=True),'prompts':prompts.model_dump(mode='json',by_alias=True) if prompts else None,'resources':resources.model_dump(mode='json',by_alias=True) if resources else None,'ping':'passed'}
        calls=params if command=='batch' else [{'name':name,'arguments':params}]
        if not isinstance(calls,list) or not 1<=len(calls)<=3:raise ValueError('Не более трёх исследовательских вызовов за одну команду.')
        prepared=[]
        for item in calls:
            n=item['name'];a=item.get('arguments',{})
            if n not in ALLOWED or n not in catalog:raise ValueError('Метод не входит в подтверждённый набор Pendar.')
            errors=list(Draft202012Validator(catalog[n].input_schema).iter_errors(a))
            if errors:raise ValueError('Параметры не соответствуют текущей схеме Pendar.')
            prepared.append((n,a))
        result=[]
        for n,a in prepared:
            r=await s.call_tool(n,arguments=a);dumped=r.model_dump(mode='json',by_alias=True)
            result.append({'name':n,'arguments':a,'result':dumped})
            if r.is_error:break
        return result[0]['result'] if command=='call' else {'ok':not any(x['result'].get('isError') for x in result),'calls':result,'same_mcp_session':True}

def main():
    p=argparse.ArgumentParser(prog='pendar-bn');p.add_argument('command',choices=['status','catalog','call','batch','profiles']);p.add_argument('--name');p.add_argument('--profile');p.add_argument('--params',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    try:
        profiles=json.loads((P/'config/profiles.json').read_text()) if (P/'config/profiles.json').exists() else {}
        params=json.loads(a.params.read_text()) if a.params else {}
        if a.profile:
            v=profiles[a.profile];a.command='call';a.name=v['name'];params={**v.get('arguments',{}),**params}
            if any(k not in params for k in v.get('required_inputs',[])):raise ValueError('Не заданы обязательные параметры выбранного профиля.')
        if a.command=='status':
            from tools.mcp_oauth import HermesTokenStorage
            result={'mcp_url':'https://pendar.ai/mcp','authentication':'independent Hermes BN OAuth','tokens_cached':HermesTokenStorage('pendar').has_cached_tokens(),'scope':'tools:read','selected_tools':sorted(ALLOWED),'profiles':len(profiles),'verification':json.loads((P/'config/verification.json').read_text()) if (P/'config/verification.json').exists() else {}}
        elif a.command=='profiles':result=profiles
        else:result=asyncio.run(run(a.command,a.name,params))
        text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text);a.output.chmod(0o600);print(a.output)
        else:print(text,end='')
        if result.get('ok') is False or result.get('isError'):sys.exit(2)
    except Exception as e:
        while isinstance(e,BaseExceptionGroup) and e.exceptions:e=e.exceptions[0]
        print(json.dumps({'ok':False,'error_type':type(e).__name__,'error':'Вызов Pendar не выполнен. Проверьте завершение входа, параметры, баланс и доступность сервиса.'},ensure_ascii=False),file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
