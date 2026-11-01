"""Portable own-profile cutover; no dependency on historical test operators."""
import json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def quiescent(cfg):
 path=Path(cfg['state_root'])/'memory.sqlite'
 if not path.is_file():raise PermissionError('initialize_platform_before_service_configuration')
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  models=db.execute('SELECT state,count(*) FROM model_attempts GROUP BY state').fetchall() if 'model_attempts' in tables else []
  active=[(s,n) for s,n in models if s not in {'returned_usage_known','outcome_unknown','aborted_before_executor','rejected_before_executor'}]
  tasks=db.execute("SELECT id FROM native_tasks WHERE state IN ('running','launch_reserved')").fetchall() if 'native_tasks' in tables else []
 if active or tasks:raise PermissionError('finish_or_pause_own_work_before_cutover')
 return {'active_native_tasks':0,'historical_unknown_outcomes_preserved':True}
def stop_for_cutover():
 legacy=ROOT/'Development/evidence/w4-20261026/gateway.pid.json'
 if legacy.exists() and (ROOT/'Development/w4_runtime.py').exists():
  import psutil
  def exited():
   try:return psutil.Process(json.loads(legacy.read_text())['pid']).status()==psutil.STATUS_ZOMBIE
   except psutil.NoSuchProcess:return True
  if exited():return {'managed_local_W4_gateway':True,'stopped':{'already_exited':True}}
  import w4_runtime
  try:stopped=w4_runtime.main(['gateway-stop'])
  except RuntimeError as exc:
   if str(exc)!='own_process_shutdown_pending_no_forced_kill' or not exited():raise
   stopped={'already_exited':True,'forced':False}
  return {'managed_local_W4_gateway':True,'stopped':stopped}
 from gateway.status import get_running_pid
 if get_running_pid(ROOT/'data/gateway.pid',cleanup_stale=False):raise PermissionError('stop_this_profile_gateway_before_service_configuration')
 return {'managed_local_W4_gateway':False,'gateway_was_stopped':True}
def restart_previous(state):
 if state['managed_local_W4_gateway']:
  import w4_runtime
  return w4_runtime.main(['gateway-start'])
 return {'automatic_gateway_start':False,'next':'Start your own configured gateway after setup; no token or owner copied.'}
