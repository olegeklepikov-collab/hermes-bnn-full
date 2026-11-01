"""Native MemoryProvider API v2; same checkpoint authority as the explicit child adapter."""
from agent.memory_provider import MemoryProvider
from agent.compression_checkpoint import current_checkpoint_input
from pathlib import Path


class CheckpointProvider(MemoryProvider):
    pre_compress_checkpoint_api_version = 2
    name = 'bnn-memory-checkpoint'

    def __init__(self, host):
        self.host = host
        self.sid = None

    def is_available(self):
        self.host.admission.profile_hash()
        return True

    def initialize(self, session_id, **kwargs):
        if not kwargs.get('hermes_home') or str(Path(kwargs['hermes_home']).resolve()) != self.host.admission.profile_home:
            raise PermissionError('checkpoint_provider_profile_mismatch')
        self.sid = session_id

    def on_session_switch(self, new_session_id, **kwargs):
        self.sid = new_session_id

    def get_tool_schemas(self):
        return []

    def on_pre_compress(self, messages, *, require_checkpoint=False):
        source = current_checkpoint_input()
        if source is None or not self.sid or source.session_id != self.sid:
            raise PermissionError('native_checkpoint_source_required')
        return self.host.checkpoints.save(source, messages)
