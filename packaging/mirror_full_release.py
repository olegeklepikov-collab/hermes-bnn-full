"""Mirror an already published, signed neutral release inside GitHub; never overwrite assets."""
from pathlib import Path
import hashlib,json,os,re,subprocess,tempfile,time
from publish_candidate import bound_release
SOURCE='olegeklepikov-collab/hermes-bnn-full'
DESTINATION='olegeklepikov-collab/hermes-bnn-full-private'
ROOT=Path(__file__).resolve().parents[1]
METADATA=['RELEASE.json','RELEASE.json.sig','PARTS.json','PARTS.json.sig','QUALIFICATION-SUMMARY.json','QUALIFICATION-SUMMARY.json.sig','allowed_signers','INSTALL.md']

def api(path,body=None,method='POST',optional=False):
    args=['gh','api',path]
    if body is None:
        result=subprocess.run(args,text=True,capture_output=True)
    else:
        with tempfile.NamedTemporaryFile('w',suffix='.json') as f:
            json.dump(body,f);f.flush()
            result=subprocess.run(args+['--method',method,'--input',f.name],text=True,capture_output=True)
    if result.returncode:
        if optional and 'HTTP 404' in result.stderr:return None
        raise RuntimeError('GitHub outcome requires observation: '+result.stderr[-500:])
    return json.loads(result.stdout)

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    tag=os.environ['BNN_MIRROR_TAG']
    if os.environ.get('GITHUB_REPOSITORY')!=DESTINATION or not re.fullmatch('bnn-[0-9]+[.][0-9]+[.][0-9]+',tag):
        raise PermissionError('explicit_canonical_private_repository_and_release_tag_required')
    index=json.loads((ROOT/'CURRENT-RELEASE.json').read_text())
    source=api(f'repos/{SOURCE}/releases/tags/{tag}')
    if source['draft'] or source['tag_name']!=tag:raise PermissionError('published_source_required')
    source_assets={a['name']:a for a in source['assets']}
    if len(source_assets)!=len(source['assets']):raise PermissionError('ambiguous_source_assets')
    with tempfile.TemporaryDirectory(prefix='bnn-release-mirror-') as directory:
        work=Path(directory)
        def download(name):
            if Path(name).name!=name or name not in source_assets:raise PermissionError('unsafe_or_missing_asset')
            asset=source_assets[name];path=work/name
            if not path.exists():
                subprocess.run(['gh','release','download',tag,'--repo',SOURCE,'--pattern',name,'--dir',str(work)],check=True)
            if asset['state']!='uploaded' or path.stat().st_size!=asset['size'] or asset.get('digest')!='sha256:'+digest(path):
                raise PermissionError('source_asset_changed:'+name)
            return path
        for name in METADATA:download(name)
        trust=ROOT/'trust/allowed_signers'
        if (work/'allowed_signers').read_bytes()!=trust.read_bytes():raise PermissionError('unexpected_signer')
        for name in ['RELEASE.json','PARTS.json','QUALIFICATION-SUMMARY.json']:
            subprocess.run(['ssh-keygen','-Y','verify','-f',str(trust),'-I','bnn-release','-n','bnn-release-v1','-s',str(work/(name+'.sig'))],input=(work/name).read_bytes(),capture_output=True,check=True)
        release=json.loads((work/'RELEASE.json').read_text());parts=json.loads((work/'PARTS.json').read_text());qualification=json.loads((work/'QUALIFICATION-SUMMARY.json').read_text())
        archive=release['archive'];marker='mirror_archive_sha256='+archive['sha256']
        if (archive['sha256']!=index['full_release']['archive_sha256'] or archive['name']!=index['full_release']['archive_name']
            or release['source_commit']!=index['runtime_source_commit'] or release.get('owner_data_included') or release.get('credentials_included')
            or parts['archive']!=archive or qualification['archive_sha256']!=archive['sha256']):raise PermissionError('release_identity_changed')
        if len(parts['parts'])!=index['full_release']['parts'] or sum(p['bytes'] for p in parts['parts'])!=archive['bytes']:
            raise PermissionError('incomplete_parts')
        for number,part in enumerate(parts['parts'],1):
            name=archive['name']+f'.part{number:03d}';asset=source_assets.get(name,{})
            if part['name']!=name or asset.get('size')!=part['bytes'] or asset.get('digest')!='sha256:'+part['sha256']:
                raise PermissionError('signed_part_not_on_source_server')
        destination=bound_release(api(f'repos/{DESTINATION}/releases?per_page=100'),None,DESTINATION,tag)
        if destination is None:
            destination=api(f'repos/{DESTINATION}/releases',{'tag_name':tag,'target_commitish':os.environ['GITHUB_SHA'],'name':'Hermes BNN '+release['version']+': verified neutral mirror','body':'Зеркало тех же подписанных байтов полного нейтрального выпуска. Проверки и ограничения: QUALIFICATION-SUMMARY.json. Автоматического обновления рабочего экземпляра нет.\n\n'+source['html_url']+'\n\n'+marker,'draft':True,'prerelease':source['prerelease'],'make_latest':'false'})
        if marker not in destination.get('body',''):raise PermissionError('existing_release_has_different_binding')
        rid=destination['id']
        expected=METADATA+[p['name'] for p in parts['parts']]
        for name in expected:
            existing=[a for a in api(f'repos/{DESTINATION}/releases/{rid}/assets?per_page=100') if a['name']==name]
            wanted=source_assets[name]
            if existing:
                if len(existing)!=1 or existing[0]['state']!='uploaded' or existing[0]['size']!=wanted['size'] or existing[0].get('digest')!=wanted['digest']:
                    raise PermissionError('existing_asset_differs_no_overwrite:'+name)
                continue
            if not destination['draft']:raise PermissionError('published_destination_is_incomplete')
            path=download(name)
            attempt=subprocess.run(['gh','release','upload',tag,str(path),'--repo',DESTINATION],capture_output=True,text=True,env={**os.environ,'GODEBUG':'http2client=0'})
            for _ in range(4):
                observed=[a for a in api(f'repos/{DESTINATION}/releases/{rid}/assets?per_page=100') if a['name']==name]
                if len(observed)==1 and observed[0]['state']=='uploaded' and observed[0].get('digest')==wanted['digest'] and observed[0]['size']==wanted['size']:break
                time.sleep(1)
            else:raise RuntimeError('upload_unconfirmed_no_blind_retry:'+name+':'+attempt.stderr[-300:])
            if name not in METADATA:path.unlink()
        current={a['name']:a for a in api(f'repos/{DESTINATION}/releases/{rid}/assets?per_page=100')}
        if not all(current[n]['state']=='uploaded' and current[n]['digest']==source_assets[n]['digest'] and current[n]['size']==source_assets[n]['size'] for n in expected):
            raise PermissionError('final_mirror_mismatch')
        published=api(f'repos/{DESTINATION}/releases/{rid}',{'draft':False,'prerelease':source['prerelease'],'make_latest':'false'},method='PATCH')
        result={'passed':True,'source':source['html_url'],'mirror':published['html_url'],'assets_verified':len(expected),'archive_sha256':archive['sha256'],'body_uploads_not_blindly_repeated':True}
        print(json.dumps(result))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
