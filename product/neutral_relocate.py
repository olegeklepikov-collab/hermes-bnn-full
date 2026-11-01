"""Relocate copied executables and local configuration, leaving signed SDK sources intact."""
import hashlib,json,os,stat,re
from pathlib import Path
from neutral_prepare import save,sha

def replace_paths(text,mapping):
 replacement=dict(mapping)
 pattern=re.compile('(?:'+'|'.join(re.escape(k) for k in replacement)+r')(?=/|$|[\'"\n])')
 return pattern.sub(lambda m:replacement[m.group()],text)

def run(bundle,old_root,refresh_original=False):
 root=bundle/'Hermes';changes=[];links=[];blocked=[]
 signed=['GSD/vendor/','UDR/software/foundation-release/foundation-source/','UDR/software/research-release/research-source/']
 mapping=[('__HERMES_ROOT__',str(root)),('__USER_HOME__',str(Path.home())),(str(old_root),str(root)),('/Volumes/AgentRuntime2/active-runtime/Hermes BN',str(root)),('/Volumes/AgentRuntime2/active-runtime/Hermes UDR',str(root/'UDR'))]
 blueprint=json.loads((bundle/'configuration/copy-plan.json').read_text())
 source_root=blueprint.get('source_root')
 if source_root and source_root!=str(old_root):mapping.append((source_root,str(root)))
 def program_file(relative):return relative in blueprint['files'] or any(relative==t or relative.startswith(t+'/') for t in blueprint['trees'])
 # Long paths and spaces in shebangs must use the standard Python shell trampoline.
 for base,ds,fs in os.walk(root,followlinks=False):
  for name in ds+fs:
   p=Path(base)/name
   if not p.is_symlink():continue
   if not program_file(str(p.relative_to(root))):continue
   target=os.readlink(p);new=target
   for before,after in mapping:
    if target.startswith(before+'/'):new=after+target[len(before):];break
   if new.startswith(str(root)+'/'):new=os.path.relpath(new,p.parent)
   if new!=target:
    # Atomic replacement of a copied program link, not deletion of owner data.
    temporary=p.with_name(p.name+'.relocating');temporary.symlink_to(new);os.replace(temporary,p);links.append(str(p.relative_to(root)))
  for name in fs:
   p=Path(base)/name
   if p.is_symlink() or not p.is_file():continue
   if p.stat().st_size>32*1024*1024:continue
   relative=str(p.relative_to(root))
   if not program_file(relative):continue
   original=old_root/relative
   refresh=refresh_original and (relative in blueprint['files'] or any(relative.startswith(t+'/') for t in blueprint['trees'])) and original.is_file()
   raw=original.read_bytes() if refresh else p.read_bytes()
   if b'\0' in raw[:8192]:continue
   try:text=raw.decode('utf-8')
   except UnicodeDecodeError:continue
   new=replace_paths(text,mapping)
   if relative.startswith('Memory/releases/'):
    continue
   if relative.startswith(tuple(signed)):
    if new!=text:blocked.append(relative)
    continue
   # Copied cache/build provenance is not account configuration.
   # Current owner's home is resolved by declared placeholders, never redacted here.
   if '/bin/' in relative and new.startswith('#!'):
    line,sep,rest=new.partition('\n')
    if ('/bin/python' in line or '/bin/python3' in line) and str(root) in line:
     executable=line[2:].strip();new='#!/bin/sh\n\'\'\'exec\' '+repr(executable)+' "$0" "$@"\n\' \'\'\'\n'+rest
   if new.encode()!=p.read_bytes():p.write_text(new);changes.append(relative)
 if blocked:raise PermissionError('signed_source_requires_external_path_adapter:'+repr(blocked[:15]))
 # All versioned Memory sources stay byte-identical; runtime binding is external.
 identity=root/'Identity/releases/0.2.1';im=json.loads((identity/'manifest.json').read_text());save(identity/'manifest.json',{name:sha(identity/name) for name in im})
 # GSD host adapter has no supplier manifest; its immutable Engine vendor remains unchanged.
 save(bundle/'configuration/relocation.json',{'relocated_links':len(links),'relocated_text_files':len(changes),'signed_source_modified':False,'build_root':str(root),'requires_relocation_after_copy':True})
 return {'relocated_links':len(links),'relocated_text_files':len(changes),'signed_source_modified':False}
