"""Operator-declared same-owner root aliases; never a new file permission."""
from pathlib import Path

def operating_path(config,value):
    path=Path(value);mappings=config.get('path_relocations',[])
    if not mappings:return path
    if not isinstance(mappings,list) or len(mappings)>4:raise PermissionError('path_relocation_contract_invalid')
    root=Path(config['package_root']).resolve().parents[2];matched=[]
    for rule in mappings:
        if not isinstance(rule,dict) or set(rule)!={'from','to','owner_id'}:raise PermissionError('path_relocation_contract_invalid')
        source=Path(rule['from']);target=Path(rule['to'])
        if not source.is_absolute() or len(source.parts)<3 or '..' in source.parts or not target.is_absolute() or '..' in target.parts:raise PermissionError('path_relocation_root_invalid')
        if target.resolve()!=root or rule['owner_id']!=config['namespace']['owner_id']:raise PermissionError('path_relocation_owner_or_root_mismatch')
        if path.is_absolute() and path.is_relative_to(source):
            relative=path.relative_to(source)
            if '..' in relative.parts:raise PermissionError('path_relocation_traversal_denied')
            result=target/relative
            if not result.resolve().is_relative_to(root):raise PermissionError('path_relocation_symlink_escape_denied')
            matched.append(result)
    if len(matched)>1:raise PermissionError('path_relocation_ambiguous')
    return matched[0] if matched else path
