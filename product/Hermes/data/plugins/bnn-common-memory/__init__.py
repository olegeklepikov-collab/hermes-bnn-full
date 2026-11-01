"""Profile-scoped entry point; settings and code must belong to the operator's copy."""
import hashlib
import json
import sys
from pathlib import Path


def register(ctx):
    settings=Path(ctx.get_config('config_file')).resolve(strict=True)
    config=json.loads(settings.read_text())
    package=Path(config['package_root']).resolve(strict=True)
    for name,checksum in json.loads((package/'manifest.json').read_text()).items():
        path=package/name
        if not path.resolve().is_relative_to(package) or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
            raise RuntimeError('common_memory_package_integrity_failed')
    sys.path.insert(0,str(package))
    from bn_memory.plugin import register as connect
    connect(ctx)
