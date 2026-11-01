"""Install into the isolated profile's plugins directory; select memory.provider by name."""
from agent.memory_provider import MemoryProvider
from bn_memory.checkpoint_provider import CheckpointProvider
from bn_memory.plugin import Host
from hermes_cli.config import load_config_readonly


class Provider(CheckpointProvider):
    def __init__(self):
        settings = load_config_readonly().get('memory', {}).get('checkpoint_settings_file')
        if not settings:
            raise RuntimeError('checkpoint_settings_file_required')
        super().__init__(Host(settings))

    def shutdown(self):
        self.host.close()


def register(ctx):
    ctx.register_memory_provider(Provider())
