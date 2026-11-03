"""Static operator-captured schemas; optional packages are imported only after admission."""
import json
from bn_memory.store import canonical
def register(host,ctx):
    for schema in host.config.get('module_tool_catalog',[]):
        name=schema['name']
        def execute(args,_name=name,**kw):
            from agent.tool_attempt import current_tool_attempt
            attempt=current_tool_attempt()
            if attempt is None or not attempt.active.is_set() or attempt.tool_name!=_name or attempt.profile_home!=host.admission.profile_home:raise PermissionError('native_module_tool_attempt_required')
            sid=attempt.identity['session_id'];turn=attempt.identity['turn_id']
            if _name=='work_plan':
                from bn_memory.task_authority import Tasks
                host.store.writable(sid);host.admission.ready(sid,turn)
                return canonical(Tasks(host).plan(sid,args))
            if _name=='work_team':
                from bn_memory.base_work import BaseWork
                return canonical(BaseWork(host).call(sid,turn,args))
            module='gsd' if _name.startswith('gsd_') else 'research'
            host.modules.require(sid,module)
            if module=='gsd':
                from bn_memory.gsd_module import get
                result=get(host).call(sid,turn,_name,args)
            else:
                from bn_memory.research_module import Research
                if not hasattr(host,'_research_module'):host._research_module=Research(host)
                result=host._research_module.call(sid,turn,_name,args)
            return canonical(result)
        ctx.register_tool(name=name,toolset='bnn_modules',schema=schema,handler=execute)
