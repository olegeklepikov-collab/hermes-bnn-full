"""Full, profile-scoped child products; display summaries may be shortened separately."""
import hashlib
from pathlib import Path

MAX_PRODUCT_BYTES=8*1024*1024

def preserve_text_product(text):
    from hermes_constants import get_hermes_home
    from tools.spill_safety import write_text_exclusive
    raw=text.encode('utf-8');digest=hashlib.sha256(raw).hexdigest()
    if len(raw)>MAX_PRODUCT_BYTES:
        return {'contract':'SubagentTextProductV1','error':'split_product_required','bytes':len(raw)}
    root=get_hermes_home()/'cache/subagent-products'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.is_symlink():raise PermissionError('unsafe_subagent_product_root')
    root.chmod(0o700)
    path=root/(digest+'.txt')
    if path.exists():
        if path.is_symlink() or path.read_bytes()!=raw:raise PermissionError('subagent_product_collision')
    else:
        try:write_text_exclusive(path,text,private=True)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=raw:raise PermissionError('subagent_product_collision')
    return {'contract':'SubagentTextProductV1','path':str(path),'sha256':digest,'bytes':len(raw)}

def read_text_product(result):
    """Read an immutable native result, without using its display summary as a contract."""
    from hermes_constants import get_hermes_home
    product=result.structured_payload
    if not isinstance(product,dict) or product.get('contract')!='SubagentTextProductV1':
        raise ValueError('full_subagent_product_required')
    if product.get('error'):raise ValueError(product['error'])
    path=Path(product.get('path',''));root=get_hermes_home()/'cache/subagent-products'
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise PermissionError('subagent_product_outside_profile')
    size=product.get('bytes')
    if type(size) is not int or not 0<=size<=MAX_PRODUCT_BYTES or path.stat().st_size!=size:
        raise ValueError('subagent_product_size_mismatch')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=product.get('sha256'):raise ValueError('subagent_product_hash_mismatch')
    return raw.decode('utf-8')
