import asyncio,json,sys,psutil
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
P=Path(__file__).resolve().parents[1]
async def main():
 async with stdio_client(StdioServerParameters(command=str(P/'bin/mcp-server-bn'),args=[])) as streams:
  async with ClientSession(streams[0],streams[1],read_timeout_seconds=300) as s:
   await s.initialize(); await s.send_ping()
   failed=await s.call_tool('btw_tool_run_r',arguments={'code':'sentinel <- 17; plot(1:3,1:3,main="R error control",xlab="x",ylab="y"); warning("Hermes BN synthetic warning"); stop("Hermes BN expected synthetic error"); sentinel <- 99','_intent':'Проверить явное сообщение об ошибке и сохранение графика'})
   dump=failed.model_dump(mode='json',by_alias=True)
   assert failed.is_error
   assert any(x['type']=='image' for x in dump['content'])
   text='\n'.join(x['text'] for x in dump['content'] if x['type']=='text')
   assert 'Hermes BN expected synthetic error' in text and 'Hermes BN synthetic warning' in text
   recovery=await s.call_tool('btw_tool_run_r',arguments={'code':'stopifnot(sentinel==17); list(previous_assignment=sentinel,recovery_mean=mean(1:5))','_intent':'Проверить состояние после ошибки и продолжение работы'})
   assert not recovery.is_error
   await s.send_ping()
   result={'expected_error':dump,'recovery':recovery.model_dump(mode='json',by_alias=True),'error_flag_checked':True,'image_and_warning_preserved':True,'partial_assignment_checked':True,'ping_before_and_after_checked':True}
   f=P/'checks/error-controls.json';f.write_text(json.dumps(result,ensure_ascii=False,indent=2));f.chmod(0o600)
   print('ERROR_CONTROLS_PASSED',flush=True)
 await asyncio.sleep(1)
 own=[]
 for proc in psutil.process_iter(['pid','cmdline']):
  if any(str(P/'scripts/server.R')==x for x in (proc.info['cmdline'] or [])):own.append(proc.pid)
 print('R_SERVERS_AFTER_CLIENT_CLOSED',own,flush=True)
 assert not own
asyncio.run(main())
