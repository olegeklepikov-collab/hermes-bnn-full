"""Atomic pre-dispatch guard for exact repeats with an unsettled physical outcome.

Scope is one owner database and native profile, independent of session/work/call ID.
Native work_team adds the durable primary work binding to its operation identity.
This is exact JSON identity, not inferred physical equivalence or outcome verification.
"""
import json
from bn_memory.admission import canonical, digest

EFFECTS = {'write_local', 'send_external', 'manage_runtime'}
UNKNOWN = ('admitted_outcome_unsettled', 'admission_rejected_outcome_unsettled', 'returned_error_outcome_unsettled', 'returned_pending_native_end')


def install(db):
    db.execute('''CREATE TABLE action_fingerprints(
        profile_id TEXT NOT NULL,nonce TEXT NOT NULL,tool_name TEXT NOT NULL,
        arguments_sha256 TEXT NOT NULL,PRIMARY KEY(profile_id,nonce),
        FOREIGN KEY(profile_id,nonce) REFERENCES action_attempts(profile_id,nonce))''')
    db.execute('CREATE INDEX action_fingerprints_lookup ON action_fingerprints(profile_id,tool_name,arguments_sha256)')
    db.execute("INSERT INTO meta VALUES('action_retry_contract','1')")


def verify(db):
    marker = db.execute("SELECT value FROM meta WHERE key='action_retry_contract'").fetchone()
    if marker is None or marker[0] != '1':
        raise RuntimeError('explicit_action_retry_migration_required')
    db.execute('SELECT profile_id,nonce,tool_name,arguments_sha256 FROM action_fingerprints LIMIT 0')


def arguments_hash(tool, args):
    # Only this host's defined MCP memory interface has trusted volatile fields.
    # All other tools retain every argument, including similarly named fields.
    from bn_memory.schemas import SCHEMAS
    if tool in {'mcp__context__' + name for name in SCHEMAS}:
        args = {key: value for key, value in args.items() if key not in {'_host', '_runtime'}}
    return digest(canonical(args))


def returned_error(value):
    """Explicit error envelopes cannot prove absence of an effect before the error."""
    if isinstance(value, str):
        try: value = json.loads(value)
        except (ValueError, TypeError): return False
    if not isinstance(value, dict): return False
    return (value.get('error') not in (None, False, '') or value.get('ok') is False
            or value.get('success') is False or value.get('is_error') is True or value.get('isError') is True)


def reserve(db, profile, nonce, tool, args):
    """Caller holds BEGIN IMMEDIATE, before publishing the final admission."""
    verify(db)
    fingerprint = arguments_hash(tool, args)
    previous = db.execute('''SELECT a.nonce,f.arguments_sha256
        FROM action_attempts a LEFT JOIN action_fingerprints f
        ON f.profile_id=a.profile_id AND f.nonce=a.nonce
        WHERE a.profile_id=? AND a.tool_name=? AND a.nonce<>?
        AND a.effect IN (?,?,?) AND a.status IN (?,?,?,?)
        AND (f.arguments_sha256=? OR f.nonce IS NULL)
        ORDER BY a.created,a.nonce''',
        (profile, tool, nonce, *sorted(EFFECTS), *UNKNOWN, fingerprint)).fetchall()
    from bn_memory.action_review import consume, start_native
    # work_team(action=run) is an operation on the bound Beads work, not a global
    # singleton. New sessions for the SAME work still cannot repeat an unknown run.
    work = None
    if tool == 'work_team':
        work = db.execute('SELECT work_id FROM working_actions WHERE profile_id=? AND nonce=?',(profile,nonce)).fetchone()
        if work is None:raise PermissionError('working_task_binding_required')
    for prior in previous:
        if work is not None:
            prior_work=db.execute('SELECT work_id FROM working_actions WHERE profile_id=? AND nonce=?',(profile,prior['nonce'])).fetchone()
            if prior_work is not None and prior_work[0]!=work[0]:continue
        if prior['arguments_sha256'] is not None and consume(db, profile, prior, nonce): continue
        # No arguments, source text or provider secrets enter the rejection.
        reason = 'unknown_legacy_arguments' if prior['arguments_sha256'] is None else 'exact_operation'
        raise PermissionError('unsettled_effect_blocks_retry:' + reason + ':' + prior['nonce'])
    old = db.execute('SELECT tool_name,arguments_sha256 FROM action_fingerprints WHERE profile_id=? AND nonce=?',
                     (profile, nonce)).fetchone()
    if old is not None:
        if (old['tool_name'], old['arguments_sha256']) != (tool, fingerprint):
            raise PermissionError('final_operation_fingerprint_changed')
    else:
        db.execute('INSERT INTO action_fingerprints VALUES(?,?,?,?)', (profile, nonce, tool, fingerprint))
    start_native(db, profile, nonce)
