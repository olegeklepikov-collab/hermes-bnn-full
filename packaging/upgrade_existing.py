"""Operator upgrade from the qualified dev.45 profile, using a whole signed release.

No account import, fresh-owner initialization, history rewind or automatic service stop.
The operator stops the exact profile first. All preimages remain private beside it.
"""
import argparse,copy,hashlib,json,os,shutil,sqlite3,stat,subprocess,sys,zipfile
from contextlib import closing
from pathlib import Path
import release_cli as release


def logical_database(path):
    """Every SQL row and schema, including accounting, not selected friendly counters."""
    result={}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise PermissionError('database_integrity_failed')
        schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        result['schema']=hashlib.sha256(json.dumps(schema,ensure_ascii=False).encode()).hexdigest()
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted='"'+name.replace('"','""')+'"'
            rows=[]
            for row in db.execute('SELECT * FROM '+quoted):
                values=[{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} if isinstance(v,bytes) else v for v in row]
                rows.append(json.dumps(values,ensure_ascii=False,separators=(',',':'),allow_nan=False))
            h=hashlib.sha256()
            for row in sorted(rows):h.update(row.encode()+b'\n')
            result[name]={'rows':len(rows),'sha256':h.hexdigest()}
    return result


def backup_database(source,target):
    if target.exists():raise FileExistsError('new_backup_required')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)) as incoming,closing(sqlite3.connect(target)) as outgoing:
        incoming.backup(outgoing)
    target.chmod(0o600)
    return logical_database(target)


def owned(root,path):
    path=Path(path).absolute()
    if path==root or not path.is_relative_to(root) or any(p.is_symlink() for p in [path,*path.parents]):
        raise PermissionError('upgrade_requires_owned_nonsymlink_path')
    return path


def restore_preimages(root,checkpoint,before):
    for name,item in before.items():
        if item.get('exists',True) and release.digest(checkpoint/'files'/name)!=item['sha256']:
            raise PermissionError('rollback_preimage_corrupt')
        owned(root,root/name)
    for name,item in before.items():
        if item.get('exists',True):shutil.copy2(checkpoint/'files'/name,root/name)
        elif (root/name).exists():
            retained=checkpoint/'retained-new-files'/name;retained.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            (root/name).rename(retained)


def rebind(config,root,package):
    cfg=copy.deepcopy(config);cfg['package_root']=str(package)
    aliases=cfg.setdefault('path_relocations',[])
    alias={'from':'/opt/hermes-bnn-distribution','to':str(root),'owner_id':cfg['namespace']['owner_id']}
    if alias not in aliases:aliases.append(alias)
    for module in cfg.get('modules',{}).values():
        files={}
        for name,h in module.get('files',{}).items():
            path=Path(name)
            if path.is_relative_to(root/'Memory/releases'):
                suffix=Path(*path.relative_to(root/'Memory/releases').parts[1:]);path=package/suffix;h=release.digest(path)
            files[str(path)]=h
        module['files']=files
    return cfg


def verify_old(root,cfg):
    package=owned(root,cfg['package_root'])
    if package.name!='2.0.0-dev.45':raise PermissionError('only_qualified_dev45_upgrade_supported')
    for name,h in release.read(package/'manifest.json').items():
        if release.digest(owned(package,package/name))!=h:raise PermissionError('old_memory_program_changed:'+name)
    old=release.read(package/'release.json')
    for name,h in old['core_patch_sha256'].items():
        if release.digest(owned(root,root/'hermes-agent'/name))!=h:raise PermissionError('old_core_program_changed:'+name)
    # This derivative was added to the versioned core pins in dev.47.
    watchdog=root/'hermes-agent/gateway/shutdown_watchdog.py'
    if release.digest(watchdog)!='13262070225a3174ae56bebefc03ed70ee0dc090d20b8bf8c005d6b49e66f7fa':
        raise PermissionError('old_watchdog_not_qualified')
    return package


def execute(root,directory,checkpoint,authority):
    root=root.resolve(strict=True);checkpoint=owned(root,checkpoint)
    permit=release.read(authority)
    if permit.get('operation')!='upgrade_existing' or permit.get('authorized_root')!=str(root):
        raise PermissionError('explicit_own_production_authority_required')
    manifest=release.verify_release(directory);bundle=directory/'Hermes-BNN-Full'
    if release.digest(bundle/'bundle-manifest.json')!=manifest['bundle_manifest_sha256']:
        raise PermissionError('wrong_whole_program_manifest')
    cfg=release.read(root/'Memory/settings.json');verify_old(root,cfg)
    if Path(cfg['profile_home'])!=root/'data':raise PermissionError('primary_profile_required')
    memory=manifest['components']['Memory'];intake=manifest['components']['Intake']
    incoming=bundle/'Hermes/Memory/releases'/memory;target=root/'Memory/releases'/memory
    library=root/'Intake'/intake
    if checkpoint.exists():raise FileExistsError('unfinished_or_previous_upgrade_observe_before_retry')
    expected=release.read(bundle/'bundle-manifest.json')['objects']
    paths={}
    for name in release.read(incoming/'manifest.json'):
        if release.digest(incoming/name)!=expected['Hermes/Memory/releases/'+memory+'/'+name]['sha256']:
            raise PermissionError('incoming_memory_changed')
    for name,h in release.read(incoming/'release.json')['core_patch_sha256'].items():
        source=bundle/'Hermes/hermes-agent'/name
        if release.digest(source)!=h:raise PermissionError('incoming_core_changed')
        current=root/'hermes-agent'/name
        if release.digest(current)!=h:paths[str(current.relative_to(root))]=source
    # All copied program bytes come from this exact whole-release inventory.
    if release.digest(incoming/'manifest.json')!=expected['Hermes/Memory/releases/'+memory+'/manifest.json']['sha256']:
        raise PermissionError('incoming_manifest_changed')
    distribution=release.read(bundle/'Intake/packages/manifest.json');wheel=bundle/'Intake/packages'/distribution['wheel']
    if release.digest(bundle/'Intake/packages/manifest.json')!=expected['Intake/packages/manifest.json']['sha256']:
        raise PermissionError('incoming_intake_manifest_changed')
    if release.digest(wheel)!=distribution['wheel_sha256'] or distribution['version']!=intake:
        raise PermissionError('incoming_intake_changed')
    sys.path[:0]=[str(root/'Intake/0.14.4'),str(root/'hermes-agent'),cfg['package_root']]
    from bnn_intake.deployment import stopped,common_plugin_target,preservation_witness
    from bnn_intake.bootstrap import verify_deployment
    from bnn_intake.recovery import optional_stopped
    verify_deployment(root/'data',root/'Memory/settings.json',cfg)
    plugin=common_plugin_target(root,root/'data')
    names=['Memory/settings.json','data/config.yaml','data/intake-deployment.json','data/.env','bin/hermes',*paths]
    names += [str((plugin/n).relative_to(root)) for n in ['__init__.py','plugin.yaml','common_policy.py']]
    dbfile=owned(root,Path(cfg['state_root'])/'memory.sqlite')
    # A live loader holds this lock; no forceful lock cleanup is permitted.
    with stopped(root,root/'data',True),optional_stopped(root,cfg):
        checkpoint.mkdir(parents=True,mode=0o700)
        before={}
        for name in names:
            path=owned(root,root/name)
            if name in {'bin/hermes','data/.env'} and not path.exists():
                before[name]={'exists':False};continue
            if not path.is_file():raise PermissionError('required_preimage_missing:'+name)
            saved=checkpoint/'files'/name;saved.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(path,saved)
            before[name]={'sha256':release.digest(saved),'mode':stat.S_IMODE(saved.stat().st_mode)}
        dbbefore=backup_database(dbfile,checkpoint/'memory.sqlite')
        preservation=preservation_witness(dbfile)
        release.write(checkpoint/'before.json',{'contract':'BNNExistingUpgradePreimageV1','root':str(root),'archive_sha256':manifest['archive']['sha256'],'source_commit':manifest['source_commit'],'files':before,'database':dbbefore,'database_sha256':release.digest(checkpoint/'memory.sqlite'),'authority_sha256':release.digest(authority),'rollback_rewinds_database':False})
    # Rehearsal runs separately with new modules loaded; no original profile writes.
    if target.exists():
        if release.inventory(target)!=release.inventory(incoming):raise PermissionError('retained_program_not_exact_candidate')
    else:shutil.copytree(incoming,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if library.exists():
        files={str(p.relative_to(library)):release.digest(p) for p in library.rglob('*') if p.is_file()}
        if files!=distribution['members_sha256']:raise PermissionError('retained_Intake_not_exact_candidate')
    else:subprocess.run([str(root/'hermes-agent/venv/bin/python'),'-B',str(bundle/'Intake/packages/unpack.py'),'--wheel',str(wheel),'--expected-sha256',distribution['wheel_sha256'],'--target',str(library)],check=True,capture_output=True)
    newcfg=rebind(cfg,root,target)
    # The executable and model-visible schemas must change together. Preserve
    # every other owner setting and module schema.
    declarations=release.read(bundle/'configuration/memory.template.json')['module_tool_catalog']
    fresh={entry['name']:entry for entry in declarations}
    newcfg['module_tool_catalog']=[fresh[e['name']] if e['name'] in {'work_team','udr_team'} else e
                                   for e in cfg['module_tool_catalog']]
    for rule in newcfg['tool_policy']['rules']:
        if rule['id'] in {'w3.module.work_team','w3.module.udr_team'}:
            rule['arguments_schema']=copy.deepcopy(fresh[rule['tool']]['parameters'])
    release.write(checkpoint/'candidate-settings.json',newcfg)
    env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','LANG','LC_ALL','TMPDIR'}}
    env.update(HERMES_HOME=str(root/'data'),PYTHONPATH=os.pathsep.join([str(library),str(target),str(root/'hermes-agent')]),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    command=[str(root/'hermes-agent/venv/bin/python'),'-B',str(Path(__file__).absolute()),'apply','--root',str(root),'--checkpoint',str(checkpoint)]
    with (checkpoint/'apply.log').open('w') as log:
        run=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
    if run.returncode:
        # No service/model was started and no live data migration is performed in
        # this qualified transition. Restore only verified program/config preimages.
        restore_preimages(root,checkpoint,before)
        release.write(checkpoint/'failure.json',{'configuration_and_programs_restored':True,'primary_database_untouched_by_rollback':True,'observe_apply_log_before_retry':True})
        raise RuntimeError('upgrade_failed_prior_program_restored_observe_private_checkpoint')
    return release.read(checkpoint/'installed.json')


def apply(root,checkpoint):
    import yaml
    from bnn_intake.deployment import stopped,write,enroll,preservation_witness,write_app_config,LOADER,MANIFEST,common_plugin_target
    from bnn_intake.recovery import optional_stopped
    from bnn_intake.bootstrap import verify_native,verify_deployment
    from bnn_intake.storage import install as migrate
    from bn_memory.store import Store
    from bn_memory.backend_policy import resource_hash
    old=release.read(checkpoint/'files/Memory/settings.json');cfg=release.read(checkpoint/'candidate-settings.json')
    before=release.read(checkpoint/'before.json');root=root.resolve()
    if before['root']!=str(root):raise PermissionError('wrong_upgrade_root')
    # Exact database backup is parsed with the new adapter, then restored to a NEW
    # file and reread. The live primary is never overwritten by this test.
    rehearsal=checkpoint/'rehearsal';rehearsal.mkdir(mode=0o700)
    initial=backup_database(checkpoint/'memory.sqlite',rehearsal/'memory.sqlite')
    trial={**cfg,'state_root':str(rehearsal)};migration=migrate(Store(rehearsal,trial))
    after=logical_database(rehearsal/'memory.sqlite')
    if initial!=after:raise PermissionError('unexpected_schema_or_data_change_requires_separate_upgrade')
    restored=backup_database(rehearsal/'memory.sqlite',checkpoint/'restored/memory.sqlite')
    if restored!=before['database']:raise PermissionError('restored_data_not_equal')
    with Store(checkpoint/'restored',trial).db() as db:db.execute('SELECT count(*) FROM records').fetchone()
    with stopped(root,root/'data',True),optional_stopped(root,old):
        if logical_database(Path(old['state_root'])/'memory.sqlite')!=before['database']:
            raise PermissionError('primary_changed_since_snapshot')
        for name,item in before['files'].items():
            if not item.get('exists',True):
                if (root/name).exists():raise PermissionError('configuration_changed_during_upgrade')
            elif release.digest(root/name)!=item['sha256']:raise PermissionError('configuration_changed_during_upgrade')
        # Core delta is intentionally narrow and byte-pinned to the whole release.
        source=Path(cfg['package_root'])/'release.json';pins=release.read(source)['core_patch_sha256']
        current=root/'hermes-agent/gateway/shutdown_watchdog.py'
        candidate=release.ROOT/'product/Hermes/hermes-agent/gateway/shutdown_watchdog.py'
        if release.digest(candidate)!=pins['gateway/shutdown_watchdog.py']:raise PermissionError('operator_source_not_candidate')
        shutil.copy2(candidate,current)
        for name,entry in cfg['backend_policy']['allow'].items():entry['resource_sha256']=resource_hash(cfg,name)
        verify_native(cfg)
        app=yaml.safe_load((root/'data/config.yaml').read_text())
        app['mcp_servers']['context']['args'][0]=str(Path(cfg['package_root'])/'bn_memory/server.py')
        app['mcp_servers']['context'].setdefault('env',{})['PYTHONPATH']=os.pathsep.join([cfg['package_root'],str(root/'hermes-agent')])
        app['plugins']['entries']['bn-common-memory']['settings']['intake_library']=str(Path(__import__('bnn_intake').__file__).parent.parent)
        plugin=common_plugin_target(root,root/'data')
        (plugin/'__init__.py').write_text(LOADER)
        (plugin/'plugin.yaml').write_text(MANIFEST.replace('0.11.0',__import__('bnn_intake').__version__))
        from bnn_intake.common_policy import standalone_source
        (plugin/'common_policy.py').write_text(standalone_source())
        # Use the native CLI entry already generated by the complete installer;
        # the historical W4 launcher remains available, but is no longer active.
        launcher='''#!/bin/bash
set -eu
hermes_install_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$hermes_install_root/environment.sh"
exec "$hermes_install_root/hermes-agent/venv/bin/python" -m hermes_cli.main "$@"
'''
        (root/'bin/hermes').write_text(launcher);(root/'bin/hermes').chmod(0o700)
        from hermes_cli.config import save_env_value,get_env_value
        token=Path(cfg['delivery']['telegram_key_file'])
        if token.is_file():
            value=token.read_text().strip();existing=get_env_value('TELEGRAM_BOT_TOKEN')
            if existing and existing!=value:raise PermissionError('native_telegram_token_differs_from_current_delivery_authority')
            save_env_value('TELEGRAM_BOT_TOKEN',value)
            save_env_value('TELEGRAM_ALLOWED_USERS',str(cfg['delivery']['recipient_user_id']))
            save_env_value('TELEGRAM_ALLOW_ALL_USERS','false');save_env_value('GATEWAY_ALLOW_ALL_USERS','false')
        write(root/'Memory/settings.json',cfg);write_app_config(root/'data/config.yaml',app)
        enroll(root,root/'Memory/settings.json');verify_deployment(root/'data',root/'Memory/settings.json',cfg)
        from bn_memory.plugin import Host
        host=Host(root/'Memory/settings.json')
        try:
            for module in cfg['modules']:host.modules._verify_enable(module)
        finally:host.close()
        if logical_database(Path(cfg['state_root'])/'memory.sqlite')!=before['database']:
            raise PermissionError('upgrade_altered_existing_history')
        receipt={'contract':'BNNExistingUpgradeReceiptV1','root':str(root),'Memory':__import__('bn_memory').__version__,'Intake':__import__('bnn_intake').__version__,'source_commit':before['source_commit'],'archive_sha256':before['archive_sha256'],'operator_source_commit':release.git('rev-parse','HEAD'),'operator_sha256':release.digest(__file__),'migration_rehearsed':migration,'all_existing_sql_rows_preserved':True,'database_restored_and_reread_in_separate_file':True,'secrets_identity_and_projects_replaced':False,'whole_environment_backup_claimed':False,'checkpoint':str(checkpoint),'gateway_restart_pending':True}
        receipt['after_files']={n:release.digest(root/n) if (root/n).is_file() else None for n in before['files']}
        write(checkpoint/'installed.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False))


def rollback(root,checkpoint):
    """Configuration/code rollback only. Never restore old accounting or user data."""
    before=release.read(checkpoint/'before.json');after=release.read(checkpoint/'installed.json')
    if before['root']!=str(root.resolve()):raise PermissionError('wrong_rollback_root')
    from bnn_intake.deployment import stopped
    with stopped(root,root/'data',True):
        for name,h in after['after_files'].items():
            path=owned(root,root/name);actual=release.digest(path) if path.is_file() else None
            if actual!=h:raise PermissionError('rollback_configuration_changed_requires_review')
        restore_preimages(root,checkpoint,before['files'])
    return {'configuration_restored':True,'current_database_untouched':True,'new_program_files_retained_inactive':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','apply','rollback']);p.add_argument('--root',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--release',type=Path);p.add_argument('--authority',type=Path);a=p.parse_args()
    if a.action=='install':v=execute(a.root,a.release,a.checkpoint,a.authority)
    elif a.action=='apply':return apply(a.root,a.checkpoint)
    else:v=rollback(a.root,a.checkpoint)
    print(json.dumps(v,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
