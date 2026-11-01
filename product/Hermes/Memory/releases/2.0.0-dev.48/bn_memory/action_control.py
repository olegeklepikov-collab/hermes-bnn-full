"""Neutral native action admission. Rules are operator state, never model assertions."""
import dataclasses
import json
import time

from jsonschema import Draft202012Validator
from agent.tool_attempt import current_tool_attempt
from bn_memory.admission import canonical, digest
from bn_memory.record_metadata import ROLES

READ_EFFECTS = {'read_local', 'query_remote'}
EFFECTS = READ_EFFECTS | {'write_local', 'send_external', 'manage_runtime'}
CHILD_FORBIDDEN = {'terminal', 'execute_code', 'delegate_task', 'send_message', 'cronjob', 'skill_manage'}


def install(connection):
    from bn_memory.control_schema import install as create
    create(connection, 'action_grants', 'action_attempts')
    connection.execute("INSERT INTO meta VALUES('neutral_action_contract','1')")
    from bn_memory.action_retry import install as install_retry
    install_retry(connection)
    from bn_memory.action_review import install as install_reviews
    install_reviews(connection)
    from bn_memory.rpc_admission import install as install_rpc
    install_rpc(connection)


def checked_schema(value):
    if not isinstance(value, dict):
        raise ValueError('action_arguments_schema_must_be_object')
    def inspect(node):
        if isinstance(node, dict):
            if {'$ref', '$dynamicRef'} & node.keys():
                raise ValueError('action_schema_references_not_supported')
            for key,child in node.items():
                if key not in {'const','enum','default','examples'}:inspect(child)
        elif isinstance(node, list):
            for child in node: inspect(child)
    inspect(value)
    Draft202012Validator.check_schema(value)
    return Draft202012Validator(value)


class ActionControl:
    def __init__(self, host):
        self.host = host
        policy = host.config.get('tool_policy', {'version': 1, 'rules': []})
        if not isinstance(policy, dict) or set(policy) != {'version', 'rules'} or type(policy['version']) is not int or policy['version'] != 1 or not isinstance(policy['rules'], list):
            raise ValueError('neutral_action_policy_invalid')
        self.rules = {}
        for rule in policy['rules']:
            if not isinstance(rule, dict) or set(rule) != {'id', 'tool', 'effect', 'roles', 'arguments_schema'}:
                raise ValueError('neutral_action_rule_invalid')
            if any(not isinstance(rule[k], str) or not rule[k].strip() or rule[k]!=rule[k].strip() or '*' in rule[k] for k in ['id', 'tool']):
                raise ValueError('explicit_action_rule_id_and_tool_required')
            if rule['id'] in self.rules or not isinstance(rule['effect'],str) or rule['effect'] not in EFFECTS or not isinstance(rule['roles'], list) or not rule['roles'] or any(not isinstance(role,str) or role not in ROLES for role in rule['roles']):
                raise ValueError('neutral_action_rule_invalid')
            checked_schema(rule['arguments_schema'])
            self.rules[rule['id']] = rule

    def delegation(self, role, permissions):
        if not isinstance(permissions, list):
            raise ValueError('explicit_child_tool_permissions_required')
        seen = set()
        for permission in permissions:
            if not isinstance(permission, dict) or set(permission) != {'rule_id', 'arguments_schema'}:
                raise ValueError('child_action_permission_invalid')
            identifier = permission['rule_id']
            if not isinstance(identifier,str):raise ValueError('child_action_rule_id_required')
            rule = self.rules.get(identifier)
            if rule is None or identifier in seen or role not in rule['roles'] or rule['effect'] not in READ_EFFECTS:
                raise PermissionError('child_action_permission_not_delegable')
            if rule['tool'] in CHILD_FORBIDDEN or rule['tool'].endswith(('__gsd_research', '__gsd_analyze', '__udr_research')):
                raise PermissionError('child_recursive_or_unrestricted_executor_forbidden')
            checked_schema(permission['arguments_schema']); seen.add(identifier)
        return permissions

    def _identity(self, payload, identity):
        attempt = current_tool_attempt()
        if attempt is None or not attempt.active.is_set() or attempt.profile_home != self.host.admission.profile_home:
            raise PermissionError('native_tool_attempt_required')
        self.host.admission.profile_hash()
        if attempt.tool_name != payload.get('tool_name'):
            raise PermissionError('nested_tool_requires_its_own_native_attempt')
        for key in ['session_id', 'turn_id', 'tool_call_id', 'task_id', 'api_request_id']:
            supplied = identity.get(key)
            if supplied not in (None, '') and supplied != attempt.identity.get(key):
                raise PermissionError('native_tool_identity_mismatch')
        owner = [attempt.identity.get(key) for key in ['session_id', 'turn_id', 'tool_call_id']]
        if any(not isinstance(value, str) or not value or len(value) > 512 for value in owner):
            raise PermissionError('native_tool_owner_turn_and_call_required')
        return attempt, owner

    def _permission(self, sid, turn, name, args):
        binding = self.host.store.binding(sid)
        # Data freshness can require a new model packet without revoking this
        # native turn's authority. Failed/preparing/wrong-turn admissions stay closed.
        row = self.host.admission.row(sid, turn, allow_refresh_required=True)
        snapshot = self.host.admission.snapshot(sid)
        # Authority can survive a same-turn memory write; evidence freshness is checked separately.
        if snapshot[:3] != (row['binding_hash'], row['profile_hash'], row['policy_revision']):
            raise PermissionError('tool_role_profile_or_policy_changed')
        permissions = None
        if binding['readonly']:
            with self.host.store.db() as connection:
                grant = connection.execute('SELECT permissions FROM action_grants WHERE profile_id=? AND assignment_id=?', (self.host.store.profile,binding['assignment_id'])).fetchone()
            if grant is None:
                raise PermissionError('native_child_action_grant_required')
            permissions = self.delegation(binding['role'], json.loads(grant[0]))
        clean = {k: v for k, v in args.items() if k not in {'_host', '_runtime'}} if name.startswith('mcp__context__') else args
        selected = []
        for rule in self.rules.values():
            if rule['tool'] != name or binding['role'] not in rule['roles']:
                continue
            schemas = [rule['arguments_schema']]
            if permissions is not None:
                permission = next((p for p in permissions if p['rule_id'] == rule['id']), None)
                if permission is None: continue
                schemas.append(permission['arguments_schema'])
            if Draft202012Validator({'allOf': schemas}).is_valid(clean): selected.append(rule)
        if len(selected) != 1:
            raise PermissionError('action_not_explicitly_permitted' if not selected else 'ambiguous_action_permission')
        basis = canonical([snapshot[:3], permissions])
        return selected[0], basis

    def admit(self, payload, identity):
        attempt, (sid,turn,call) = self._identity(payload, identity)
        from agent.tool_attempt import register_tool_completion
        register_tool_completion('bn-common-memory', self._complete)
        args = payload.get('args')
        if not isinstance(args, dict): raise PermissionError('tool_arguments_object_required')
        rule, basis = self._permission(sid, turn, attempt.tool_name, args)
        boundary = identity.get('boundary')
        final = boundary == attempt.final_boundary or boundary == 'bn_document_read_adapter'
        if boundary not in {'execution_middleware', 'agent_final_dispatch', 'registry', 'connector_dispatch', 'bn_document_read_adapter'}:
            raise PermissionError('known_native_tool_boundary_required')
        input_hash = digest(canonical(args))
        with self.host.store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM action_attempts WHERE profile_id=? AND nonce=?', (self.host.store.profile,attempt.nonce)).fetchone()
            if row is None:
                if boundary != 'execution_middleware' and not final:
                    raise PermissionError('native_outer_tool_admission_required')
                previous = connection.execute('SELECT status FROM action_attempts WHERE profile_id=? AND sid=? AND turn_id=? AND call_id=?', (self.host.store.profile,sid,turn,call)).fetchone()
                if previous is not None: raise PermissionError('tool_operation_already_recorded_verify_outcome_before_retry')
                connection.execute('INSERT INTO action_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (attempt.nonce, sid, turn, call, attempt.tool_name, basis, rule['id'], rule['effect'],
                     input_hash if final else None, boundary if final else None, canonical([boundary]),
                     'admitted_outcome_unsettled' if final else 'prechecked', None, time.time(),self.host.store.profile))
                from bn_memory.working import link_action
                link_action(connection,self.host.store.profile,sid,attempt.nonce)
            else:
                if row['status'] not in {'prechecked', 'admitted_outcome_unsettled'} or row['basis'] != basis:
                    raise PermissionError('tool_attempt_not_active_or_basis_changed')
                boundaries = json.loads(row['boundaries'])
                if boundary in boundaries: raise PermissionError('tool_boundary_already_admitted')
                if row['input_hash'] is not None and row['input_hash'] != input_hash:
                    raise PermissionError('tool_arguments_changed_after_final_admission')
                if row['input_hash'] is None and not final:
                    raise PermissionError('expected_final_tool_boundary_missing')
                connection.execute('UPDATE action_attempts SET rule_id=?,effect=?,input_hash=?,final_boundary=?,boundaries=?,status=? WHERE profile_id=? AND nonce=?',
                    (rule['id'], rule['effect'], input_hash, row['final_boundary'] or boundary,
                     canonical(boundaries + [boundary]), 'admitted_outcome_unsettled', self.host.store.profile,attempt.nonce))
            from bn_memory.action_retry import EFFECTS, reserve
            if final and rule['effect'] in EFFECTS:
                reserve(connection, self.host.store.profile, attempt.nonce, attempt.tool_name, args)
        return attempt.nonce

    def _complete(self, attempt):
        from bn_memory.action_review import end_native
        end_native(self.host.store, attempt)

    def abort(self, nonce):
        with self.host.store.db() as connection:
            connection.execute("UPDATE action_attempts SET status=CASE WHEN status='prechecked' THEN 'rejected_before_executor' ELSE 'admission_rejected_outcome_unsettled' END WHERE profile_id=? AND nonce=? AND status IN ('prechecked','admitted_outcome_unsettled')", (self.host.store.profile,nonce))

    def finish(self, payload, identity):
        attempt, _ = self._identity(payload, identity)
        result = payload.get('result')
        if dataclasses.is_dataclass(result): result = dataclasses.asdict(result)
        try: result_hash = digest(canonical(result))
        except (TypeError, ValueError): result_hash = None
        with self.host.store.db() as connection:
            row = connection.execute('SELECT status,input_hash,effect FROM action_attempts WHERE profile_id=? AND nonce=?', (self.host.store.profile,attempt.nonce)).fetchone()
            blocked = row is not None and row['status'] == 'prechecked' and attempt.no_dispatch.is_set()
            if not blocked and (row is None or row['status'] != 'admitted_outcome_unsettled' or row['input_hash'] is None):
                raise PermissionError('final_tool_admission_required_before_result')
            from bn_memory.action_retry import EFFECTS, returned_error
            status = 'native_blocked_before_dispatch' if blocked else 'returned_unreviewed'
            if not blocked and row['effect'] in EFFECTS and returned_error(result):
                status = 'returned_error_outcome_unsettled'
            elif not blocked and row['effect'] in EFFECTS:
                status = 'returned_pending_native_end'
            connection.execute('UPDATE action_attempts SET status=?,result_hash=? WHERE profile_id=? AND nonce=?',
                               (status, result_hash, self.host.store.profile,attempt.nonce))
