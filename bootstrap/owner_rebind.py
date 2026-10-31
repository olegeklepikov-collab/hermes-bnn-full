"""Trusted local authority refresh, without regenerating immutable program packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent/'Hermes');p.add_argument('--stopped',action='store_true');a=p.parse_args()
    root=a.root.resolve(strict=True);settings=root/'Memory/settings.json';cfg=json.loads(settings.read_text())
    sys.path[:0]=[str(root/'Intake/0.14.3'),cfg['package_root'],str(root/'hermes-agent')]
    from bnn_intake.deployment import stopped,write,enroll
    from bnn_intake.recovery import optional_stopped
    from bnn_intake.bootstrap import verify_native
    from bn_memory.backend_policy import resource_hash
    verify_native(cfg);sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    with stopped(root,cfg['profile_home'],a.stopped),optional_stopped(root,cfg):
        regpath=Path(cfg['service_integration']['registry_file'])
        if sha(regpath)!=cfg['service_integration']['registry_sha256']:raise PermissionError('Registry changed: separate catalogue/transport qualification required')
        registry=json.loads(regpath.read_text());entries={e['service']:e for e in registry['services']}
        for files in cfg['service_integration']['files'].values():
            for name,expected in files.items():
                if sha(name)!=expected:raise PermissionError('Program changed: separate source qualification required')
        for name in cfg['service_integration']['authority_hashes']:
            path=Path(entries[name]['authority_file'])
            if path.is_symlink() or not path.resolve().is_relative_to(root):raise PermissionError('Own regular authority path required')
            info=path.stat()
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise PermissionError('Owner-only authority permissions required')
            cfg['service_integration']['authority_hashes'][name]=sha(path)
        cfg['backend_policy']['allow']['embedding']['resource_sha256']=resource_hash(cfg,'embedding')
        write(settings,cfg);certificate=enroll(root,settings)
    print(json.dumps({'own_configuration_bound':True,'new_program_package_created':False,'provider_or_network_calls':0,
        'model_data_or_expenses_reset':False,'deployment_version':certificate['version']}))


if __name__=='__main__':main()
