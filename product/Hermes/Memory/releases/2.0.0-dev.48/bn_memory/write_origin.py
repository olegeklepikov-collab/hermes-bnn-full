"""Native write provenance: never accepted from model-supplied record fields."""
from contextlib import contextmanager
from contextvars import ContextVar

_ORIGIN=ContextVar('bn_native_write_origin',default=None)


@contextmanager
def rpc_origin(host,sid,nonce):
    with host.store.db() as db:
        row=db.execute("SELECT sid,turn_id,status FROM action_attempts WHERE profile_id=? AND nonce=?",(host.store.profile,nonce)).fetchone()
    if row is None or row['sid']!=sid or row['status']!='admitted_outcome_unsettled':
        raise PermissionError('native_write_origin_required')
    token=_ORIGIN.set({'profile_id':host.store.profile,'session_id':sid,'step_id':row['turn_id'],'attempt_id':nonce})
    try:yield
    finally:_ORIGIN.reset(token)


def for_binding(binding):
    value=_ORIGIN.get()
    if value is not None:
        if value['profile_id']!=binding['profile_id'] or value['session_id']!=binding['sid']:
            raise PermissionError('native_write_origin_binding_mismatch')
        return value
    return {'step_id':None,'attempt_id':None}
