"""Exact pristine program composition before any owner initialization."""
import hashlib,json,os,stat
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent;manifest=root/'bundle-manifest.json'
    expected=json.loads(manifest.read_text())['objects'];actual={}
    for base,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:
            path=Path(base)/name;relative=str(path.relative_to(root))
            if relative=='bundle-manifest.json':continue
            item={'mode':stat.S_IMODE(path.lstat().st_mode)}
            if path.is_symlink():item.update(type='symlink',target=os.readlink(path))
            elif path.is_dir():item['type']='directory'
            elif path.is_file():
                with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                item.update(type='file',bytes=path.stat().st_size,sha256=sha)
            else:raise PermissionError('unexpected_nonprogram_object:'+relative)
            actual[relative]=item
    if expected!=actual:
        changed=[p for p in expected.keys()|actual.keys() if expected.get(p)!=actual.get(p)]
        raise PermissionError('pristine_bundle_changed:'+repr(changed[:10]))
    print(json.dumps({'pristine_bundle_verified':True,'objects':len(actual),'authority':'Release archive SHA verified separately; embedded manifest is an integrity check, not an independent signature'}))
if __name__=='__main__':main()
