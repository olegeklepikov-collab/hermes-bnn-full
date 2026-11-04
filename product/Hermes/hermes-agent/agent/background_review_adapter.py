"""Profile-owned native review dispatcher. No model-created registrations."""
from pathlib import Path
import threading
import contextvars
from hermes_constants import get_hermes_home

_LOCK=threading.RLock()
_HANDLERS={}


def register(profile_home,handler):
    home=str(Path(profile_home).resolve())
    with _LOCK:
        if home in _HANDLERS:raise ValueError('background_review_adapter_already_registered')
        _HANDLERS[home]=handler
    def remove():
        with _LOCK:
            if _HANDLERS.get(home) is handler:del _HANDLERS[home]
    return remove


def prepare(agent,messages,prompt,review_memory,review_skills,review_run,explicit):
    with _LOCK:handler=_HANDLERS.get(str(get_hermes_home().resolve()))
    if handler is None:return None
    # A registered mandatory adapter may refuse. Never silently fall back to
    # the detached shared-session fork after its refusal.
    target=handler(agent=agent,messages=messages,prompt=prompt,review_memory=review_memory,
                   review_skills=review_skills,review_run=review_run,explicit=explicit)
    if not callable(target):raise RuntimeError('native_review_target_required')
    context=contextvars.copy_context()
    return lambda:context.run(target)
