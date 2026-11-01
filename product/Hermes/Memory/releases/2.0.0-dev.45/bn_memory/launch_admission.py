"""Trusted launch intent is private host state, never inferred from model text or metadata."""
import contextvars
import json
from pathlib import Path
import uuid

from bn_memory.admission import digest
from bn_memory.record_metadata import ROLES

_intent = contextvars.ContextVar('bnn_trusted_launch_intent', default=None)


def check_module(host, parent, module, role):
    if module not in {'base', 'gsd', 'research'} or role in {'G', 'S', 'D'} and module != 'gsd':
        raise PermissionError('assignment_module_invalid')
    policy = host.admission.policy(parent)
    if module == 'gsd' and policy['gsd_mode'] == 'off':
        raise PermissionError('gsd_disabled_for_session')
    if module == 'research' and not policy['research_enabled']:
        raise PermissionError('research_disabled_for_session')
    if module!='base' and host.config.get('w3_enabled'):host.modules.require(parent,module)

def trusted_start(host,parent,goal,module):
    token=_intent.get()
    if not token or token[:2]!=(str(host.store.root.resolve()),host.store.profile):raise PermissionError('trusted_launch_intent_required')
    with host.store.db() as db:row=db.execute('SELECT * FROM launch_grants WHERE profile_id=? AND id=?',(host.store.profile,token[2])).fetchone()
    if not row or row['state']!='prepared' or row['parent_sid']!=parent or row['module']!=module or row['goal_hash']!=digest(goal):raise PermissionError('trusted_module_job_required')
    return row['id']


def fail_grant(host, identifier):
    with host.store.db() as connection:
        row = connection.execute('SELECT child_sid FROM launch_grants WHERE profile_id=? AND id=?', (host.store.profile,identifier)).fetchone()
        connection.execute("UPDATE launch_grants SET state='failed' WHERE profile_id=? AND id=?", (host.store.profile,identifier))
        if row and row[0]:
            connection.execute("UPDATE sessions SET role='unassigned',assignment_id='',purpose='',context=NULL,turn=NULL WHERE profile_id=? AND sid=?", (host.store.profile,row[0]))
            connection.execute("UPDATE context_admissions SET status='failed' WHERE profile_id=? AND sid=?", (host.store.profile,row[0]))


def admit(host, payload, identity):
    token = _intent.get()
    if not token or token[:2] != (str(host.store.root.resolve()),host.store.profile):
        raise PermissionError('trusted_launch_intent_required')
    with host.store.db() as connection:
        grant = connection.execute('SELECT * FROM launch_grants WHERE profile_id=? AND id=?', (host.store.profile,token[2])).fetchone()
    if grant is None or grant['state'] != 'prepared':
        raise PermissionError('launch_grant_not_prepared')
    grant = dict(grant)
    parent = identity.get('session_id')
    if parent != grant['parent_sid'] or identity.get('turn_id') != grant['parent_turn']:
        raise PermissionError('launch_parent_turn_mismatch')
    host.store.writable(parent)
    host.admission.ready(parent, grant['parent_turn'])
    check_module(host, parent, grant['module'], grant['role'])
    handle = payload.get('handle', {})
    route=token[3] if len(token)>3 else {}
    if any(handle.get(key)!=value for key,value in route.items()):
        raise PermissionError('native_launch_route_mismatch')
    if handle.get('parent_session_id') != parent or handle.get('role') != 'leaf' or handle.get('depth') != 1:
        raise PermissionError('native_leaf_role_and_depth_required')
    if digest(payload.get('goal', '')) != grant['goal_hash'] or handle.get('correlation_id') != grant['id']:
        raise PermissionError('launch_input_mismatch')
    child_sid = identity.get('child_session_id')
    child = host.store.binding(child_sid)
    if child['parent'] != parent or not child['readonly']:
        raise PermissionError('native_child_binding_required')
    with host.store.db() as connection:
        changed = connection.execute("UPDATE launch_grants SET state='admitted',child_sid=?,subagent_id=? WHERE profile_id=? AND id=? AND state='prepared'",
                                      (child_sid, handle.get('subagent_id'), host.store.profile,grant['id'])).rowcount
    if changed != 1:
        raise PermissionError('launch_grant_already_used')
    try:
        host.store.assign(parent, child_sid, grant['role'], grant['purpose'], grant['id'])
    except BaseException:
        fail_grant(host, grant['id'])
        raise
    return grant['id']


def launch(host, service, *, parent_sid, turn_id, goal, analytical_role, purpose,
           module='base', allowed_toolsets=None, tool_permissions=None,model=None,provider=None,resources=None,correlation_id=None,expected_resources_hash=None):
    """Only trusted GSD/UDR/base adapters call this function; it is not a model tool."""
    from agent.subagent_lifecycle import SubagentLaunchRequest
    host.store.writable(parent_sid)
    host.admission.ready(parent_sid, turn_id)
    if analytical_role not in ROLES or analytical_role == 'parent' or not isinstance(purpose, str) or not purpose.strip():
        raise ValueError('assignment_contract_invalid')
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError('assignment_goal_required')
    route={key:value for key,value in [('model',model),('provider',provider)] if value is not None}
    if any(not isinstance(value,str) or not value.strip() for value in route.values()):raise ValueError('assignment_route_invalid')
    check_module(host, parent_sid, module, analytical_role)
    permissions=host.actions.delegation(analytical_role,tool_permissions if tool_permissions is not None else [])
    controls = json.loads((Path(host.admission.profile_home) / 'execution-controls.json').read_text())
    controller = host.config.get('launch_controller_id', 'bn-common-memory')
    if controller not in controls.get('required', {}).get('subagent_launch', []):
        raise PermissionError('mandatory_native_launch_control_required')
    identifier = correlation_id or uuid.uuid4().hex
    if not isinstance(identifier,str) or not __import__('re').fullmatch(r'[A-Za-z0-9_.-]{1,128}',identifier):raise ValueError('trusted_correlation_id_invalid')
    if host.config.get('w3_enabled'):
        from bn_memory.assignment_resources import prepare
        prepared=prepare(host,parent_sid,analytical_role,identifier,resources)
        if expected_resources_hash is not None and digest(json.dumps(prepared,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))!=expected_resources_hash:raise PermissionError('planned_resource_version_changed')
    with host.store.db() as connection:
        connection.execute('INSERT INTO launch_grants VALUES(?,?,?,?,?,?,?,\'prepared\',NULL,NULL,?)',
                           (identifier, parent_sid, turn_id, digest(goal), analytical_role, purpose, module,host.store.profile))
        from bn_memory.admission import canonical
        connection.execute('INSERT INTO action_grants VALUES(?,?,?)',(identifier,canonical(permissions),host.store.profile))
    binding = _intent.set((str(host.store.root.resolve()),host.store.profile,identifier,route))
    try:
        handle = service.launch(SubagentLaunchRequest(goal=goal, role='leaf', allowed_toolsets=allowed_toolsets,model=model,provider=provider,
                                                    parent_session_id=parent_sid, correlation_id=identifier))
        with host.store.db() as connection:
            result = connection.execute('SELECT state,subagent_id FROM launch_grants WHERE profile_id=? AND id=?', (host.store.profile,identifier)).fetchone()
        if not result or result['state'] != 'admitted' or result['subagent_id'] != handle.subagent_id:
            service.cancel(handle, reason='Trusted launch admission missing')
            raise PermissionError('native_launch_not_admitted')
        return handle
    except BaseException:
        fail_grant(host, identifier)
        raise
    finally:
        _intent.reset(binding)
