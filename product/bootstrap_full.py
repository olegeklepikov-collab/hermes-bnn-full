"""Fresh local composition after pristine verification and relocation. No account import."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=p.with_name(p.name+'.new');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,p)


def initialize_services(bundle):
    from neutral_prepare import convert
    root=bundle/'Hermes';cfg=json.loads((root/'Memory/settings.json').read_text());owner=cfg['namespace']['owner_id']
    registry=convert(json.loads((bundle/'configuration/services.template.json').read_text()),root,owner)
    for entry in registry['services']:
        authority=Path(entry['authority_file'])
        if not authority.resolve().is_relative_to(root):raise PermissionError('fresh_service_authority_outside_own_root')
        if authority.exists():raise FileExistsError('fresh_service_authority_already_exists')
        save(authority,{'headers':{},'env':{}})
        directory=Path(entry['state_root'])
        if not directory.resolve().is_relative_to(root):raise PermissionError('fresh_service_state_outside_own_root')
        for name in ['config','checks','exports','cache','projects','documents','logs','stream-results','imports','data','downloads','content','results']:
            (directory/name).mkdir(parents=True,exist_ok=True,mode=0o700)
    save(root/'Services/registry.private.json',registry)
    integration=cfg['service_integration'];integration['registry_sha256']=sha(root/'Services/registry.private.json')
    integration['catalogue_sha256']=sha(Path(cfg['package_root'])/'services/catalogue.json')
    # All included programs were checked against the pristine inventory before
    # relocation. External native R must match the explicitly supplied release.
    expected_external=json.loads((bundle/'configuration/external-native-pins.json').read_text())
    for service,files in integration['files'].items():
        for filename in files:
            path=Path(filename)
            if not path.is_file():raise FileNotFoundError('required_service_program_missing:'+service+':'+filename)
            digest=sha(path)
            if not path.resolve().is_relative_to(root) and expected_external.get(filename)!=digest:
                raise PermissionError('external_native_program_not_the_qualified_release:'+filename)
            files[filename]=digest
    for service in integration['authority_hashes']:
        entry=next(x for x in registry['services'] if x['service']==service)
        integration['authority_hashes'][service]=sha(entry['authority_file'])
    save(root/'Memory/settings.json',cfg)
    return {'registry_entries':len(registry['services']),'empty_new_account_capsules':True,'provider_execution_verified':False}


def intake_distribution(bundle):
    manifest=json.loads((bundle/'Intake/packages/manifest.json').read_text())
    version=manifest.get('version');name=manifest.get('wheel')
    declared=json.loads((bundle/'configuration/full-source.json').read_text())['Intake']
    if (manifest.get('contract')!='BNNIntakeDistributionV1' or not isinstance(version,str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) or declared!=version
            or name!='hermes_bnn_intake-'+version+'-py3-none-any.whl'):
        raise PermissionError('intake_distribution_version_or_name_mismatch')
    return manifest,bundle/'Intake/packages'/name,bundle/'Hermes/Intake'/version


def install_intake(bundle):
    root=bundle/'Hermes';source=bundle/'Intake';cfg=json.loads((root/'Memory/settings.json').read_text());python=root/'hermes-agent/venv/bin/python'
    manifest,package,library=intake_distribution(bundle)
    library.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    subprocess.run([str(python),'-B',str(source/'packages/unpack.py'),'--wheel',str(package),'--expected-sha256',manifest['wheel_sha256'],'--target',str(library)],check=True)
    env={k:v for k,v in os.environ.items() if k in ['HOME','PATH','TMPDIR','LANG','LC_ALL']}
    env.update(HERMES_HOME=str(root/'data'),PYTHONPATH=os.pathsep.join([str(library),cfg['package_root'],str(root/'hermes-agent')]),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    code='import json,sys;from bnn_intake.deployment import install;print(json.dumps(install(sys.argv[1],sys.argv[2],library=sys.argv[3],backup_scope="activation",offline_attested=True)))'
    run=subprocess.run([str(python),'-B','-c',code,str(root),str(root/'Memory/settings.json'),str(library)],env=env,cwd=root,capture_output=True,text=True,timeout=180)
    save(root/'state/full-intake-install-process.json',{'exit_code':run.returncode})
    (root/'state/full-intake-install.log').write_text(run.stdout+run.stderr)
    if run.returncode:raise RuntimeError('fresh_intake_install_failed_inspect_own_log')
    receipt=json.loads(run.stdout.splitlines()[-1]);save(root/'state/full-intake-install.json',receipt)
    return {'version':manifest['version'],'installed':True,'one_existing_common_Host':True}


def initialize(bundle):
    from neutral_prepare import initialize as base_initialize
    result=base_initialize(bundle)
    control_file=bundle/'Hermes/data/execution-controls.json'
    controls=json.loads(control_file.read_text())
    seconds=json.loads((bundle/'configuration/execution-controls.template.json').read_text())['timeout_seconds']
    if type(seconds) is not int or not 0<seconds<=60:raise PermissionError('invalid_control_wait_bound')
    controls['timeout_seconds']=seconds;save(control_file,controls)
    services=initialize_services(bundle);intake=install_intake(bundle)
    save(bundle/'Hermes/state/full-platform-initialized.json',{'fresh_local_initialized':True,'base':result,'services':services,'intake':intake,
        'source_owner_credentials_or_identity_copied':False,'provider_or_Telegram_execution_verified':False})
    return {'fresh_local_initialized':True,'services':services,'intake':intake,'external_accounts_configured':False}


def verify(bundle):
    from neutral_prepare import verify as base_verify
    result=base_verify(bundle);root=bundle/'Hermes';cfg=json.loads((root/'Memory/settings.json').read_text())
    _,_,library=intake_distribution(bundle)
    sys.path[:0]=[str(library),cfg['package_root'],str(root/'hermes-agent')]
    from hermes_cli.plugins import discover_plugins,get_plugin_manager
    from hermes_cli.execution_control import authorize,ExecutionControlDenied
    discover_plugins();manager=get_plugin_manager();entry=manager._plugins['bn-common-memory']
    if entry.error:raise RuntimeError('full_common_plugin_failed')
    denied=[]
    for kind in ['tool','tool_result','llm','auxiliary','subagent_launch']:
        try:authorize(kind,{},session_id='fresh-full-no-grant',platform='cli')
        except ExecutionControlDenied as exc:
            if 'unavailable' in str(exc) or 'timed out' in str(exc):raise
            denied.append(kind)
        else:raise PermissionError('unbound_call_admitted')
    if not {'intake_work','intake_analysis','intake_research','intake_delegation'}<=set(manager._plugin_tool_names):raise RuntimeError('intake_tools_missing')
    manager.unload()
    value={'fresh_verification':result,'five_required_controls':denied,'Intake_registered':True,
        'fresh_owner_data_not_source_history':True,'provider_or_Telegram_execution_claimed':False}
    save(root/'state/full-platform-verification.json',value);return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['initialize','verify']);p.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parent);a=p.parse_args()
    print(json.dumps(globals()[a.action](a.bundle.resolve()),ensure_ascii=False,indent=2))
