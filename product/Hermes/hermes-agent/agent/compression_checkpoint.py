"""Native full-transcript handoff; explicit profile-scoped child checkpoint adapter.

The memory-provider v2 evidence remains normalized. Only a local checkpoint provider
opting into this API reads the full host input. No model or tool can mint this scope.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import threading

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class CheckpointInput:
    profile_home: str
    session_id: str
    parent_session_id: str
    platform: str
    messages: list


_CURRENT = ContextVar('native_compression_checkpoint_input', default=None)
_ADAPTERS = {}
_LOCK = threading.RLock()


def current_checkpoint_input():
    return _CURRENT.get()


@contextmanager
def checkpoint_input_scope(agent, messages):
    value = CheckpointInput(str(get_hermes_home().resolve()),
                            str(getattr(agent, 'session_id', '') or ''),
                            str(getattr(agent, '_parent_session_id', '') or ''),
                            str(getattr(agent, 'platform', '') or ''), messages)
    token = _CURRENT.set(value)
    try:
        yield value
    finally:
        _CURRENT.reset(token)


def register_child_checkpoint_adapter(name, callback, *, profile_home, on_compression_complete=None):
    """Register one explicit adapter per profile; unregister cannot remove a replacement."""
    home = str(Path(profile_home).resolve())
    registration = (name, callback, on_compression_complete)
    with _LOCK:
        if home in _ADAPTERS:
            raise ValueError('child_checkpoint_adapter_already_registered')
        _ADAPTERS[home] = registration

    def unregister():
        with _LOCK:
            if _ADAPTERS.get(home) is registration:
                del _ADAPTERS[home]
    return unregister


def notify_checkpoint_compression_complete(agent, *, new_session_id, old_session_id):
    """Post-commit observation only; required controllers still admit the next request."""
    if str(getattr(agent, 'session_id', '') or '') != new_session_id:
        raise ValueError('native_compression_session_mismatch')
    with _LOCK:
        registration = _ADAPTERS.get(str(get_hermes_home().resolve()))
    callback = registration[2] if registration else None
    if not callable(callback):
        return False
    callback(session_id=new_session_id, old_session_id=old_session_id,
             platform=str(getattr(agent, 'platform', '') or 'cli'))
    return True


def child_checkpoint_adapter_available(agent):
    if (getattr(agent, 'platform', '') != 'subagent' or not getattr(agent, '_parent_session_id', '')
            or not getattr(agent, 'session_id', '')):
        return False
    with _LOCK:
        return str(get_hermes_home().resolve()) in _ADAPTERS


def child_checkpoint_context(evidence_messages):
    value = current_checkpoint_input()
    if value is None or value.platform != 'subagent' or not value.parent_session_id or not value.session_id:
        return None
    with _LOCK:
        registration = _ADAPTERS.get(str(get_hermes_home().resolve()))
    if registration is None:
        return None
    result = registration[1](value, evidence_messages)
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError('child_checkpoint_adapter_receipt_required')
    return result
