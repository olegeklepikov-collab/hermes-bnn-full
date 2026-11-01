"""Session module switches. Base protection/data remain independent of optional modules."""
import hashlib,json,re,time
from pathlib import Path
from bn_memory.store import canonical,sha

class Modules:
    def __init__(self,host):
        self.host=host;self.store=host.store;self.active={};self.file_checks={}
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS module_attempts(profile_id TEXT,sid TEXT,id TEXT,module TEXT,bead TEXT,input_hash TEXT,state TEXT,body TEXT,PRIMARY KEY(profile_id,id))')
            db.execute('CREATE TABLE IF NOT EXISTS module_mode_events(profile_id TEXT,sid TEXT,revision INTEGER,module TEXT,desired TEXT,actor TEXT,at REAL,PRIMARY KEY(profile_id,sid,revision))')
    def track(self,identifier,sid,module,service,handle):
        # A slash command runs outside the parent's model-turn ContextVar. Capture
        # the genuine owner at launch, then rebind ONLY for its own cancellation.
        import weakref
        from agent.subagent_lifecycle import get_active_subagent_parent,bind_subagent_parent
        owner=get_active_subagent_parent()
        if owner is None or owner.session_id!=sid:raise PermissionError('active_native_parent_required')
        ref=weakref.ref(owner);home=self.host.admission.profile_home
        class ScopedCancellation:
            def cancel(self,handle,reason):
                from hermes_constants import get_hermes_home
                actual=ref()
                if actual is None or actual.session_id!=sid or str(get_hermes_home().resolve())!=home:
                    raise PermissionError('own_active_native_parent_unavailable')
                with bind_subagent_parent(actual):return service.cancel(handle,reason=reason)
        self.active[identifier]=(sid,module,ScopedCancellation(),handle)

    def require(self,sid,module):
        if module not in {'gsd','research'}:raise ValueError('module_invalid')
        policy=self.host.admission.policy(sid,create=True)
        if module=='gsd' and policy['gsd_mode']=='off':raise PermissionError('gsd_disabled_for_session')
        if module=='research' and not policy['research_enabled']:raise PermissionError('research_and_foundation_disabled_for_session')
        return self._verify_enable(module)
    def status(self,sid):
        self.store.writable(sid);policy=self.host.admission.policy(sid,create=True)
        with self.store.db() as db:jobs=[dict(r) for r in db.execute("SELECT id,module,bead,state FROM module_attempts WHERE profile_id=? AND sid=? AND state IN ('preparing','running','unknown','launch_reserved','cancelling')",(self.store.profile,sid))]
        with self.store.db() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='native_tasks'").fetchone():jobs += [dict(r) for r in db.execute("SELECT id,bead,state,COALESCE(json_extract(body,'$.module'),'research') AS module FROM native_tasks WHERE profile_id=? AND root_sid=? AND state IN ('running','unknown','launch_reserved')",(self.store.profile,sid))]
        modes={}
        for name,enabled in [('gsd',policy['gsd_mode']!='off'),('research',bool(policy['research_enabled']))]:
            pending=[r for r in jobs if r['module']==name]
            modes[name]={'desired':'on' if enabled else 'off','actual':'draining_or_unknown' if pending and not enabled else 'off' if not enabled else 'available' if name in self.host.config.get('modules',{}) else 'unavailable',
                         'unfinished':pending,'reason':'optional_module_unconfigured' if enabled and name not in self.host.config.get('modules',{}) else None}
        return {'scope':'session','session_id':sid,'profile_id':self.store.profile,'revision':policy['revision'],'GSD_mode':policy['gsd_mode'],
                'UDR_and_Foundation_enabled':bool(policy['research_enabled']),'modules':modes,'base_protection_enabled':True,'automatic_replay':False,
                'shared_model_resource':self.host.accounting.status(sid) if hasattr(self.host,'accounting') else {'status':'not_configured_in_fixture'}}
    def set(self,sid,module,enabled,expected,actor):
        if module not in {'gsd','research'} or type(enabled)is not bool or type(expected)is not int:raise ValueError('module_switch_contract_invalid')
        if not isinstance(actor,str) or not actor:raise PermissionError('authenticated_command_actor_required')
        self.store.writable(sid)
        if enabled:self.require(sid,module) if self._enabled(sid,module) else self._verify_enable(module)
        previous=self.host.admission.policy(sid,create=True)
        if previous['revision']!=expected:raise ValueError('policy_revision_conflict')
        gsd=('auto' if enabled else 'off') if module=='gsd' else previous['gsd_mode']
        research=enabled if module=='research' else bool(previous['research_enabled'])
        policy=self.host.admission.revise_policy(sid,expected,gsd,research)
        if policy['revision']!=previous['revision']:
            with self.store.db() as db:db.execute('INSERT INTO module_mode_events VALUES(?,?,?,?,?,?,?)',(self.store.profile,sid,policy['revision'],module,'on' if enabled else 'off',actor,time.time()))
        cancelled=[]
        if not enabled:
            for identifier,(root,kind,service,handle) in list(self.active.items()):
                if root==sid and kind==module:
                    outcome=service.cancel(handle,reason='Explicit session module off')
                    cancelled.append({'id':identifier,'requested':outcome.accepted,'terminal':outcome.already_terminal,'unknown_handle':outcome.unknown_handle,'unsupported':outcome.unsupported,'native_state':getattr(outcome.state,'value',outcome.state)})
            if module=='research':
                with self.store.db() as db:
                    table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_bindings'").fetchone()
                    runs=[r[0] for r in db.execute("SELECT id FROM research_bindings WHERE profile_id=? AND sid=? AND state='active'",(self.store.profile,sid))] if table else []
                for run in runs:
                    try:
                        self._verify_enable('research')
                        from bn_memory.research_module import Research
                        value=Research(self.host).pause(sid,run)
                        cancelled.append({'id':run,'research_paused':True,'lease':value.get('lease')})
                    except Exception as exc:
                        cancelled.append({'id':run,'research_paused':False,'state':'unknown','reason':str(exc)})
        return {**self.status(sid),'cancellation_requests':cancelled}
    def _enabled(self,sid,module):
        p=self.host.admission.policy(sid,create=True);return p['gsd_mode']!='off' if module=='gsd' else bool(p['research_enabled'])
    def research(self,sid):
        if not self._enabled(sid,'research'):return None
        binding=self.store.binding(sid);root=binding
        while root['parent']:root=self.store.binding(root['parent'])
        if binding['readonly']:
            with self.store.db() as db:grant=db.execute('SELECT module FROM launch_grants WHERE profile_id=? AND id=?',(self.store.profile,binding['assignment_id'])).fetchone()
            if not grant or grant[0]!='research':return None
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='research_bindings'").fetchone():return None
            if not db.execute("SELECT 1 FROM research_bindings WHERE profile_id=? AND sid=? AND state='active'",(self.store.profile,root['sid'])).fetchone():return None
        self.require(sid,'research')
        if not hasattr(self.host,'_research_module'):
            from bn_memory.research_module import Research
            self.host._research_module=Research(self.host)
        return self.host._research_module
    def _verify_enable(self,module):
        # Inspect the conditional files without importing or starting the module.
        config=self.host.config.get('modules',{}).get(module)
        if not config:raise PermissionError('optional_module_unconfigured:'+module)
        for name,expected in config['files'].items():
            p=Path(name)
            if not p.is_file() or p.is_symlink():raise PermissionError('optional_module_integrity_failed:'+module)
            st=p.stat();stamp=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,expected)
            if self.file_checks.get(name)!=stamp:
                with p.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
                if actual!=expected:raise PermissionError('optional_module_integrity_failed:'+module)
                self.file_checks[name]=stamp
        return config
    def command(self,module,raw,identity):
        if identity['profile_home']!=self.host.admission.profile_home:raise PermissionError('command_profile_mismatch')
        sid=identity['session_id'];self.store.bind(sid);self.store.writable(sid)
        parts=raw.split();action=parts[0] if parts else 'status'
        if action=='status':return canonical(self.status(sid))
        allowed={'auto','off'} if module=='gsd' else {'on','off'}
        if action not in allowed:raise ValueError('use /gsd auto|off|status or /udr on|off|status')
        if len(parts) not in {1,3} or len(parts)==3 and parts[1]!='--revision':raise ValueError('invalid_module_command')
        expected=int(parts[2]) if len(parts)==3 else self.host.admission.policy(sid,create=True)['revision']
        return canonical(self.set(sid,module,action!='off',expected,identity['actor']))

def command_identity(host):
    from gateway.session_context import get_session_env
    from hermes_constants import get_hermes_home
    home=str(get_hermes_home().resolve());platform=get_session_env('HERMES_SESSION_PLATFORM','')
    sid=get_session_env('HERMES_SESSION_ID','');user=get_session_env('HERMES_SESSION_USER_ID','')
    if platform and platform not in {'cli','terminal'}:
        if user not in host.config.get('command_owners',[]):raise PermissionError('module_command_owner_required')
        if not sid:
            key=get_session_env('HERMES_SESSION_KEY','')
            if not key:raise PermissionError('native_command_session_required')
            from hermes_state import SessionDB
            db=SessionDB()
            try:rows=db.load_gateway_routing_entries(scope=str(Path(home)/'sessions'))
            finally:db.close()
            if key not in rows:raise PermissionError('start_native_conversation_before_changing_its_mode')
            entry=json.loads(rows[key]);sid=entry['session_id']
            if str(entry.get('origin',{}).get('user_id'))!=user:raise PermissionError('command_routing_actor_mismatch')
    if not sid:raise PermissionError('native_command_session_required')
    return {'session_id':sid,'actor':platform+':'+user if platform not in {'','cli','terminal'} else 'local-native-cli','profile_home':home}

def register(host,ctx):
    for command,module in [('gsd','gsd'),('udr','research')]:
        def handle(raw,_module=module):return host.modules.command(_module,raw,command_identity(host))
        ctx.register_command(command,handle,description='Режим текущей беседы; общая защита и память сохраняются',args_hint='auto|on|off|status')
