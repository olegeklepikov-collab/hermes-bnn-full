"""Explicit profile-scoped provider for the stable native identity slot."""
from dataclasses import dataclass
from pathlib import Path
import threading


@dataclass(frozen=True)
class IdentityProjection:
    text: str
    reference: dict


_PROVIDERS={}
_LOCK=threading.RLock()


def register_identity_provider(profile_home,callback):
    key=str(Path(profile_home).resolve())
    with _LOCK:
        if key in _PROVIDERS:raise ValueError('identity_provider_already_registered')
        _PROVIDERS[key]=callback
    def remove():
        with _LOCK:
            if _PROVIDERS.get(key) is callback:del _PROVIDERS[key]
    return remove


def resolve_identity(agent,profile_home,context_length=None):
    from hermes_constants import get_hermes_home,set_hermes_home_override,reset_hermes_home_override
    key=str(Path(profile_home or get_hermes_home()).resolve())
    with _LOCK:callback=_PROVIDERS.get(key)
    if callback is None:return None
    token=set_hermes_home_override(Path(key))
    try:value=callback(agent,context_length=context_length)
    finally:reset_hermes_home_override(token)
    if not isinstance(value,IdentityProjection) or not value.text or not value.reference:
        raise PermissionError('required_identity_projection_not_available')
    return value


def prepare_identity_source(raw,profile_home,context_length=None):
    """Use the installed SOUL transformations, but reject loss of required identity content."""
    from agent import prompt_builder as builder
    from tools.bot_mode_probe import strip_legacy_protocol
    from hermes_cli.profile_distribution import read_manifest
    content=strip_legacy_protocol(raw).strip()
    manifest=read_manifest(Path(profile_home))
    authored=manifest is None or (bool(manifest.distribution_owned) and 'SOUL.md' not in manifest.distribution_owned)
    content=builder._scan_context_content(content,'SOUL.md',user_authored=authored)
    if not content or content.startswith('[BLOCKED:'):raise PermissionError('identity_source_not_loadable')
    if len(content)>builder._get_context_file_max_chars(context_length):
        raise PermissionError('required_identity_projection_exceeds_context_bound')
    return content
