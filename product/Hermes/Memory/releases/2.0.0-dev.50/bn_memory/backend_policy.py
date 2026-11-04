"""Explicit process/egress permissions, bound to resource identity; default deny."""
from pathlib import Path
from bn_memory.store import canonical, sha

OPERATIONS = {
    'agentmemory': {'health', 'search', 'sync'}, 'graphiti': {'health', 'search', 'sync'},
    'zvec': {'health', 'search', 'sync', 'sync_many'}, 'mirage': {'read'}, 'serena': {'read'},
    'embedding': {'query', 'document'}, 'compute': {'run'},
}
FIELDS = {
    'agentmemory': ['agentmemory_url', 'agentmemory_key_file','agentmemory_adapter','python'],
    'graphiti': ['neo4j_uri', 'neo4j_user', 'neo4j_password_file', 'graph_python'],
    'zvec': ['zvec_python'], 'mirage': ['mirage_command', 'code_path', 'projects', 'python'],
    'serena': ['serena_command', 'code_path', 'projects', 'python'],
    'embedding': ['embedding_url', 'voyage_key_file'], 'compute': ['compute_python','compute_limits'],
}


def resource_hash(config, backend):
    if backend not in FIELDS: raise ValueError('unknown_backend_resource')
    material = {key: config.get(key) for key in FIELDS[backend] + ['namespace', 'profile_home', 'state_root']}
    for key in {'neo4j_password_file','voyage_key_file','agentmemory_key_file'} & set(FIELDS[backend]):
        path=config.get(key)
        if not path:continue
        source=Path(path)
        if source.is_symlink():raise PermissionError('unsafe_backend_credential_source')
        try:info=source.stat()
        except FileNotFoundError:material[key+'_identity']='missing'
        else:material[key+'_identity']=[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_uid,info.st_mode]
    material['adapter'] = sha(Path(__file__).with_name('embeddings.py' if backend == 'embedding' else 'workers.py').read_text())
    if backend=='agentmemory' and config.get('agentmemory_adapter'):material['native_derivative']=sha(Path(config['agentmemory_adapter']).read_text())
    if backend in {'agentmemory','graphiti','zvec'}:material['readback_observer']=sha(Path(__file__).with_name('projection_observe.py').read_text())
    if backend=='zvec':
        material['prefilter_adapter']=sha(Path(__file__).with_name('vector_visibility.py').read_text())
        material['vector_validator']=sha(Path(__file__).with_name('embeddings.py').read_text())
    if backend=='compute':
        material['adapter']=sha(Path(__file__).with_name('isolated_runtime.py').read_text())
        material['worker']=sha(Path(__file__).with_name('compute_worker.py').read_text())
        material['input_guard']=sha(Path(__file__).with_name('compute.py').read_text())
        material['runtime_pin']=sha((Path(__file__).resolve().parents[1]/'compute-runtime.json').read_text())
    material['fixed_embedding_contract'] = ['voyage-4-large', 1024]
    if backend in {'embedding','zvec'}:
        from bn_memory.embedding_contract import space
        material['semantic_space']=space(config)
        material['space_adapter']=sha(Path(__file__).with_name('embedding_contract.py').read_text())
    if backend=='embedding':
        material['cache_adapter']=sha(Path(__file__).with_name('embedding_cache.py').read_text())
        material['transport_adapter']=sha(Path(__file__).with_name('workers.py').read_text())
    return sha(canonical(material))


class BackendPolicy:
    def __init__(self, config):
        self.config = config
        value = config.get('backend_policy', {'version': 1, 'allow': {}})
        if not isinstance(value, dict) or set(value) != {'version', 'allow'} or type(value['version']) is not int or value['version'] != 1 or not isinstance(value['allow'], dict):
            raise ValueError('backend_policy_invalid')
        for backend, entry in value['allow'].items():
            if backend not in OPERATIONS or not isinstance(entry, dict) or set(entry) != {'operations', 'resource_sha256'}:
                raise ValueError('backend_permission_invalid')
            if not isinstance(entry['operations'], list) or not entry['operations'] or any(not isinstance(op, str) or op not in OPERATIONS[backend] for op in entry['operations']):
                raise ValueError('backend_operation_invalid')
            digest = entry['resource_sha256']
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('backend_resource_sha256_required')
        self.allowed = value['allow']

    def permits(self, backend, operation):
        entry = self.allowed.get(backend)
        return bool(entry and operation in entry['operations'] and entry['resource_sha256'] == resource_hash(self.config, backend))

    def require(self, backend, operation):
        if not self.permits(backend, operation): raise PermissionError('backend_operation_not_approved:' + backend + ':' + operation)

    def inventory(self):
        rows=[]
        for backend in OPERATIONS:
            try:
                digest=resource_hash(self.config,backend)
                operations=sorted(op for op in OPERATIONS[backend] if self.permits(backend,op));error=None
            except OSError:
                digest=None;operations=[];error='resource_identity_unavailable'
            rows.append({'backend':backend,'resource_sha256':digest,'permitted_operations':operations,
                         'identity_error':error,'service_execution_verified':False})
        return rows
