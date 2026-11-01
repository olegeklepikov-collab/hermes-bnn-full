"""Profile-bound identity of one native tool dispatch, shared by its nested boundaries."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from threading import Event, RLock
import uuid

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class ToolAttempt:
    nonce: str
    profile_home: str
    tool_name: str
    identity: object
    final_boundary: str
    active: Event
    no_dispatch: Event
    completions: dict = field(default_factory=dict)
    completion_lock: object = field(default_factory=RLock)


_CURRENT = ContextVar('native_tool_attempt', default=None)
FINAL_BOUNDARIES = frozenset({'execution_middleware', 'agent_final_dispatch', 'registry', 'connector_dispatch'})


def current_tool_attempt():
    return _CURRENT.get()


def register_tool_completion(identifier, callback):
    attempt = _CURRENT.get()
    if attempt is None or not attempt.active.is_set():
        raise PermissionError('active_native_tool_attempt_required_for_completion')
    if not isinstance(identifier, str) or not identifier or not callable(callback):
        raise ValueError('native_tool_completion_registration_invalid')
    with attempt.completion_lock:
        if not attempt.active.is_set(): raise PermissionError('native_tool_attempt_is_closing')
        previous = attempt.completions.get(identifier)
        if previous is not None and previous != callback: raise ValueError('conflicting_native_tool_completion')
        attempt.completions[identifier] = callback


def _complete_attempt(attempt):
    attempt.active.clear()  # No recursive admission or late completion registration.
    with attempt.completion_lock:
        callbacks = tuple(attempt.completions.values())
    failures = []
    for callback in callbacks:
        try: callback(attempt)
        except BaseException as exc: failures.append(exc)
    if failures:
        from hermes_cli.execution_control import ExecutionControlDenied
        raise ExecutionControlDenied('required_tool_completion_failed') from failures[0]


def mark_tool_not_dispatched():
    attempt = _CURRENT.get()
    if attempt is not None:
        attempt.no_dispatch.set()


@contextmanager
def tool_attempt_scope(tool_name, identity, *, final_boundary='execution_middleware'):
    if final_boundary not in FINAL_BOUNDARIES:
        raise ValueError('unsupported_native_tool_final_boundary')
    active = Event(); active.set()
    attempt = ToolAttempt(uuid.uuid4().hex, str(get_hermes_home().resolve()), tool_name,
                          MappingProxyType(dict(identity)), final_boundary, active, Event())
    token = _CURRENT.set(attempt)
    try:
        yield attempt
    finally:
        try: _complete_attempt(attempt)
        finally: _CURRENT.reset(token)
