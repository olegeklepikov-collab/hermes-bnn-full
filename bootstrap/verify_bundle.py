"""Exact pristine composition, using filesystem-equivalent Unicode path identity."""
import hashlib,json,os,stat,unicodedata
from pathlib import Path

def unique_paths(objects):
    normalized={}
    for path,item in objects.items():
        key=unicodedata.normalize('NFC',path)
        if key in normalized:raise PermissionError('ambiguous_unicode_program_path:'+key)
        normalized[key]=item
    return normalized

def verify(root):
    root=Path(root);manifest=root/'bundle-manifest.json'
    expected=unique_paths(json.loads(manifest.read_text())['objects']);actual={}
    for base,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:
            path=Path(base)/name;relative=unicodedata.normalize('NFC',str(path.relative_to(root)))
            if relative=='bundle-manifest.json':continue
            if relative in actual:raise PermissionError('ambiguous_unicode_program_path:'+relative)
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
    return {'pristine_bundle_verified':True,'objects':len(actual),'unicode_filename_identity':'NFC_with_collision_rejection','authority':'Release archive SHA verified separately; embedded manifest is an integrity check, not an independent signature'}

def main():print(json.dumps(verify(Path(__file__).resolve().parent)))
if __name__=='__main__':main()
