"""Explicit operator retention for superseded program-only archives; never live state."""
import argparse,json,re
from pathlib import Path
import release_cli as r


def plan(root,keep=2):
 root=Path(root).resolve();records=[]
 for d in root.iterdir():
  if not d.is_dir() or d.is_symlink() or not (d/'RELEASE.json').is_file():continue
  v=r.read(d/'RELEASE.json');a=v.get('archive',{});name=a.get('name','')
  if Path(name).name!=name or not re.fullmatch(r'[A-Za-z0-9._-]+\.tar\.gz',name):continue
  p=d/name
  if p.is_symlink() or not p.is_file() or v.get('owner_data_included') is not False or v.get('credentials_included') is not False:continue
  version=v.get('version','');parts=version.split('-')[0].split('.')
  if len(parts)!=3 or not all(x.isdigit() for x in parts):continue
  records.append((tuple(map(int,parts)),p,v))
 records.sort(key=lambda x:x[0],reverse=True)
 return {'preserved':[str(p) for _,p,_ in records[:keep]],'eligible':[{'path':str(p),'bytes':p.stat().st_size,'sha256':v['archive']['sha256'],'build_id':v['build_id']} for _,p,v in records[keep:]],'live_data_or_expanded_trees_in_scope':False}


def apply(root,authority):
 cfg=r.resources();root=Path(root).resolve();a=r.read(authority)
 if root!=Path(cfg['build_root']).resolve()/'candidates' or a.get('operation')!='retire_program_archives' or a.get('authorized_root')!=str(root):raise PermissionError('explicit_program_archive_retention_authority_required')
 result=plan(root)
 for item in result['eligible']:
  p=Path(item['path']);v=r.verify_release(p.parent)
  if v['archive']['sha256']!=item['sha256']:raise PermissionError('changed_program_archive')
  r.write(p.parent/'LOCAL-ARCHIVE-RETIRED.json',{'reason':'Verified program-only archive superseded; latest two archives and all expanded trees retained','archive':v['archive'],'owner_state_removed':False})
  p.unlink()
 return result


def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','apply']);p.add_argument('--root',type=Path);p.add_argument('--authority',type=Path);a=p.parse_args();root=a.root or Path(r.resources()['build_root'])/'candidates'
 print(json.dumps(plan(root) if a.action=='plan' else apply(root,a.authority),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
