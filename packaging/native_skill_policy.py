"""Compile explicit parent read permission for the supplied native skill library.

No wildcard, installation, execution, external lookup or private skill-directory scan.
The native skill reader still enforces its directory and linked-file boundaries.
"""
import ast,hashlib,re
from pathlib import Path


def compile_bundled(core):
    root=Path(core).resolve()/'skills';names=[];files={}
    for path in sorted(root.rglob('SKILL.md')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise PermissionError('bundled_skill_source_escape')
        text=path.read_text();name=path.parent.name
        if text.startswith('---\n'):
            head=text.split('\n---',1)[0]
            match=re.search(r'^name:\s*(.*?)\s*$',head,re.M)
            if match:
                raw=match.group(1);name=ast.literal_eval(raw) if raw.startswith(('"',"'")) else raw
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,127}',name):
            raise PermissionError('bundled_skill_name_requires_explicit_resolution')
        if name in names:raise PermissionError('duplicate_bundled_skill_requires_explicit_resolution')
        names.append(name);files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    if not names:raise PermissionError('no_native_bundled_skills')
    rule={'id':'native.skills.bundled','tool':'skill_view','effect':'read_local','roles':['parent'],
          'arguments_schema':{'type':'object','additionalProperties':False,'properties':{
              'name':{'enum':sorted(names)},'file_path':{'type':'string','minLength':1,'maxLength':1024}},'required':['name']}}
    return rule,files
