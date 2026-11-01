"""Verify the exact Memory/Intake/core/wheel composition before a full build."""
from pathlib import Path
import ast,hashlib,json,zipfile

def verify_version(memory, expected):
    tree=ast.parse((Path(memory)/'bn_memory/__init__.py').read_text())
    versions=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets)]
    declared=json.loads((Path(memory)/'release.json').read_text())['version']
    if versions != [expected] or declared != expected or Path(memory).name != expected:
        raise PermissionError('memory_runtime_version_mismatch')

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def verify_pins(memory,core,contract):
    for root,key in [(Path(memory),'memory_files'),(Path(core),'core_files')]:
        for name,expected in contract[key].items():
            path=root/name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file() or digest(path)!=expected:
                raise PermissionError('unqualified_component_pair:'+name)

def verify_runtime_origin(compute,parser):
    origin=Path(compute['runtime_root']).parents[2]
    if not origin.is_absolute() or len(origin.parts)<3 or '..' in origin.parts:
        raise PermissionError('sealed_runtime_origin_invalid')
    for value in [compute['python'],parser['python'],*parser['python_roots']]:
        path=Path(value)
        if not path.is_absolute() or not path.is_relative_to(origin) or '..' in path.parts:
            raise PermissionError('sealed_runtime_path_not_in_origin')
    return origin

def verify_pair(root):
    root=Path(root);product=root/'product';lock=json.loads((root/'locks/product.lock.json').read_text())
    intake=product/'Intake';contract=json.loads((intake/'src/bnn_intake/data/native-compatibility.json').read_text())
    if contract['memory_version']!=lock['components']['Memory']:raise PermissionError('intake_memory_version_mismatch')
    template=json.loads((product/'configuration/memory.template.json').read_text())
    if template['package_root']!='__HERMES_ROOT__/Memory/releases/'+contract['memory_version']:
        raise PermissionError('active_memory_template_version_mismatch')
    verify_pins(product/'Hermes/Memory/releases'/contract['memory_version'],product/'Hermes/hermes-agent',contract)
    memory=product/'Hermes/Memory/releases'/contract['memory_version']
    verify_version(memory,contract['memory_version'])
    verify_pins(memory,memory,{'memory_files':json.loads((memory/'manifest.json').read_text()),'core_files':{}})
    verify_runtime_origin(json.loads((memory/'compute-runtime.json').read_text()),json.loads((memory/'parser-runtime.json').read_text()))
    distribution=json.loads((intake/'packages/manifest.json').read_text())
    if distribution['version']!=lock['components']['Intake']:raise PermissionError('intake_distribution_version_mismatch')
    name=distribution['wheel']
    if Path(name).name!=name:raise PermissionError('unsafe_intake_wheel_name')
    wheel=intake/'packages'/name
    if digest(wheel)!=distribution['wheel_sha256']:raise PermissionError('intake_wheel_hash_mismatch')
    with zipfile.ZipFile(wheel) as archive:
        if set(archive.namelist())!=set(distribution['members_sha256']):raise PermissionError('intake_wheel_members_mismatch')
        for name,expected in distribution['members_sha256'].items():
            raw=archive.read(name)
            if hashlib.sha256(raw).hexdigest()!=expected:raise PermissionError('intake_wheel_member_hash_mismatch:'+name)
            if name.startswith('bnn_intake/') and (intake/'src'/name).read_bytes()!=raw:
                raise PermissionError('intake_source_wheel_divergence:'+name)
    return {'Memory':contract['memory_version'],'Intake':distribution['version'],'core_pins_verified':len(contract['core_files']),'wheel_members_verified':len(distribution['members_sha256'])}
