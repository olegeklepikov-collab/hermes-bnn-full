"""Bind the separate identity authority to native stable delivery; no private signing key access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading

_LOCK=threading.RLock()


def load_package(root,expected_manifest):
    root=Path(root).resolve();raw=(root/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_manifest:raise PermissionError('identity_package_manifest_mismatch')
    for name,checksum in json.loads(raw).items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
            raise PermissionError('identity_package_integrity_failed')
    name='_bnn_identity_'+hashlib.sha256(str(root).encode()).hexdigest()[:20]
    with _LOCK:
        if name not in sys.modules:
            spec=importlib.util.spec_from_file_location(name,root/'bnn_identity/__init__.py',submodule_search_locations=[str(root/'bnn_identity')])
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module
            try:spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(name,None);raise
        return sys.modules[name]


class IdentityAdapter:
    def __init__(self,host):
        self.host=host;self.config=host.config['identity_runtime'];self.profile=self.config['profile']
        if self.profile!=host.store.profile or self.config['instance_id']!=host.store.namespace['owner_id']:
            raise PermissionError('identity_memory_namespace_mismatch')
        package=load_package(self.config['package_root'],self.config['package_manifest_sha256'])
        self.store=package.Store(self.config['vault_root'])
        if self.store.policy['instance_id']!=self.config['instance_id']:
            raise PermissionError('identity_instance_binding_mismatch')
        expected=str(Path(host.admission.profile_home)/'SOUL.md')
        if self.store.policy['profiles'].get(self.profile)!=expected:raise PermissionError('identity_profile_binding_mismatch')
        private=[Path(path).resolve() for path in self.config.get('private_roots',[self.store.root])]
        if not private or not any(self.store.root.is_relative_to(path) for path in private):
            raise PermissionError('identity_vault_private_root_required')
        if any(path.is_relative_to(Path(project).resolve()) for path in private for project in host.config['projects'].values()):
            raise PermissionError('identity_authority_inside_searchable_project')
        self.check_policy()

    def check_policy(self):
        raw=(self.store.root/'policy.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.config['policy_sha256']:raise PermissionError('identity_policy_changed_requires_reload')
        self.host.admission.profile_hash()

    def projection(self,sid,context_length=None):
        from agent.identity_provider import prepare_identity_source
        self.check_policy();binding=self.host.store.binding(sid)
        if binding['readonly'] and binding['role']=='unassigned':raise PermissionError('identity_native_child_assignment_required')
        if binding['readonly']:
            with self.host.store.db() as connection:
                grant=connection.execute("SELECT parent_sid,role FROM launch_grants WHERE profile_id=? AND id=? AND child_sid=? AND state='admitted'",(self.host.store.profile,binding['assignment_id'],sid)).fetchone()
            if grant is None or grant['parent_sid']!=binding['parent'] or grant['role']!=binding['role']:
                raise PermissionError('identity_native_child_assignment_required')
        def build(source,role):
            if role=='parent':return prepare_identity_source(bytes(source['content']).decode(),self.host.admission.profile_home,context_length)
            from agent.system_prompt import DEFAULT_AGENT_IDENTITY
            return DEFAULT_AGENT_IDENTITY+'\n'+json.dumps({'agent_id':self.store.policy['agent_id'],'revision':source['id'],
                               'role':role,'purpose':binding['purpose'],'identity_grants_permissions':False},ensure_ascii=False,sort_keys=True)
        return self.store.pin(self.profile,sid,binding['role'],binding['parent'] or '',build)

    def reference(self,sid):
        projection=self.projection(sid)
        return {**json.loads(projection['reference']),'view_sha256':projection['view_sha256']}

    def resolve(self,agent,context_length=None):
        from agent.identity_provider import IdentityProjection
        sid=str(getattr(agent,'session_id','') or '')
        parent=str(getattr(agent,'_parent_session_id','') or '')
        self.host.store.bind(sid,parent,subagent=getattr(agent,'platform','')=='subagent')
        projection=self.projection(sid,context_length)
        from agent import prompt_builder
        if len(projection['view'])>prompt_builder._get_context_file_max_chars(context_length):
            raise PermissionError('required_identity_projection_exceeds_context_bound')
        return IdentityProjection(projection['view'],json.loads(projection['reference']))

    def validate_request(self,sid,request):
        projection=self.projection(sid)
        from bn_memory.admission import text_parts
        text=request.get('instructions','')
        text=text if isinstance(text,str) else '\n'.join(text_parts(text))
        for row in request.get('messages',request.get('input',[])):
            if isinstance(row,dict) and row.get('role') in {'system','developer'}:
                text+='\n'+'\n'.join(text_parts(row.get('content')))
        if text.count('<BN_IDENTITY_VIEW>')!=1 or projection['view'] not in text:
            raise PermissionError('native_pinned_identity_not_delivered_in_system_slot')
        return self.reference(sid)
