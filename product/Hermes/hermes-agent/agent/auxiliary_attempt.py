"""Trusted identity of one physical auxiliary attempt, including off-turn work."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
import uuid

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class AuxiliaryAttempt:
    nonce: str
    profile_home: str
    identity: object


_CURRENT = ContextVar('native_auxiliary_attempt', default=None)


def current_auxiliary_attempt():
    return _CURRENT.get()


@contextmanager
def auxiliary_attempt_scope(identity):
    attempt = AuxiliaryAttempt(uuid.uuid4().hex, str(get_hermes_home().resolve()),
                               MappingProxyType(dict(identity)))
    token = _CURRENT.set(attempt)
    try:
        yield attempt
    finally:
        _CURRENT.reset(token)
