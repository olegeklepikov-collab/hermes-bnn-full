"""Profile-qualified control tables; record/source authority remains owner-scoped."""

SCHEMA = {
    'sessions': '''sid TEXT NOT NULL,project TEXT NOT NULL,task TEXT NOT NULL,parent TEXT,
        readonly INTEGER NOT NULL,context TEXT,turn TEXT,role TEXT NOT NULL DEFAULT 'parent',
        purpose TEXT NOT NULL DEFAULT '',assignment_id TEXT NOT NULL DEFAULT '',
        profile_id TEXT NOT NULL,PRIMARY KEY(profile_id,sid),
        FOREIGN KEY(profile_id,parent) REFERENCES sessions(profile_id,sid)''',
    'context_admissions': '''sid TEXT NOT NULL,turn_id TEXT NOT NULL,token TEXT NOT NULL,status TEXT NOT NULL,
        binding_hash TEXT NOT NULL,profile_hash TEXT NOT NULL,policy_revision INTEGER NOT NULL,
        data_epoch INTEGER NOT NULL,anchors TEXT NOT NULL,query TEXT NOT NULL,
        context_hash TEXT,envelope TEXT,retired TEXT NOT NULL,profile_id TEXT NOT NULL,
        PRIMARY KEY(profile_id,sid),FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid)''',
    'session_policy': '''sid TEXT NOT NULL,revision INTEGER NOT NULL,gsd_mode TEXT NOT NULL,
        research_enabled INTEGER NOT NULL,gsd_revision INTEGER NOT NULL,research_revision INTEGER NOT NULL,
        profile_id TEXT NOT NULL,PRIMARY KEY(profile_id,sid),
        FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid)''',
    'launch_grants': '''id TEXT NOT NULL,parent_sid TEXT NOT NULL,parent_turn TEXT NOT NULL,
        goal_hash TEXT NOT NULL,role TEXT NOT NULL,purpose TEXT NOT NULL,module TEXT NOT NULL,state TEXT NOT NULL,
        child_sid TEXT,subagent_id TEXT,profile_id TEXT NOT NULL,PRIMARY KEY(profile_id,id),
        FOREIGN KEY(profile_id,parent_sid) REFERENCES sessions(profile_id,sid),
        FOREIGN KEY(profile_id,child_sid) REFERENCES sessions(profile_id,sid)''',
    'auxiliary_admissions': '''nonce TEXT NOT NULL,sid TEXT NOT NULL,purpose TEXT NOT NULL,
        identity TEXT NOT NULL,snapshot TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,
        created REAL NOT NULL,profile_id TEXT NOT NULL,PRIMARY KEY(profile_id,nonce),
        FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid)''',
    'checkpoints': '''id TEXT NOT NULL,sid TEXT NOT NULL,sha256 TEXT NOT NULL,payload TEXT NOT NULL,
        created REAL NOT NULL,profile_id TEXT NOT NULL,PRIMARY KEY(profile_id,id),
        FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid)''',
    'action_grants': '''assignment_id TEXT NOT NULL,permissions TEXT NOT NULL,profile_id TEXT NOT NULL,
        PRIMARY KEY(profile_id,assignment_id),
        FOREIGN KEY(profile_id,assignment_id) REFERENCES launch_grants(profile_id,id)''',
    'action_attempts': '''nonce TEXT NOT NULL,sid TEXT NOT NULL,turn_id TEXT NOT NULL,call_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,basis TEXT NOT NULL,rule_id TEXT NOT NULL,effect TEXT NOT NULL,
        input_hash TEXT,final_boundary TEXT,boundaries TEXT NOT NULL,status TEXT NOT NULL,
        result_hash TEXT,created REAL NOT NULL,profile_id TEXT NOT NULL,
        PRIMARY KEY(profile_id,nonce),UNIQUE(profile_id,sid,turn_id,call_id),
        FOREIGN KEY(profile_id,sid) REFERENCES sessions(profile_id,sid)''',
}


def install(connection, *names):
    for name in names:
        connection.execute('CREATE TABLE ' + name + '(' + SCHEMA[name] + ')')
