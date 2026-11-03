"""Qualified record-memory subset; other service capabilities stay undeclared."""
import copy
from bn_memory.schemas import SCHEMAS


def memory_record_policy():
    rules = []
    children = ['collector', 'analyst', 'reviewer', 'G', 'S', 'D', 'parser', 'computation']
    def add(identifier, tool, effect, roles, narrowing=None):
        description, properties, required = SCHEMAS[tool]
        schema = {'type': 'object', 'properties': copy.deepcopy(properties),
                  'required': list(required), 'additionalProperties': False}
        if narrowing: schema = {'allOf': [schema, narrowing]}
        rules.append({'id': 'memory.' + identifier, 'tool': 'mcp__context__' + tool,
                      'effect': effect, 'roles': roles, 'arguments_schema': schema})
    add('record.parent', 'memory_record', 'write_local', ['parent'])
    add('retract.parent', 'memory_retract', 'write_local', ['parent'])
    add('status.parent', 'memory_status', 'read_local', ['parent'])
    add('recall.parent', 'memory_recall', 'query_remote', ['parent'])
    add('recall.local.child', 'memory_recall', 'read_local', children,
        {'properties': {'mode': {'const': 'local'}}, 'required': ['mode']})
    add('recall.cached.child', 'memory_recall', 'read_local', children,
        {'properties': {'mode': {'const': 'hybrid'}}, 'required': ['mode']})
    add('read.parent', 'memory_read', 'read_local', ['parent'])
    add('read.record.child', 'memory_read', 'read_local', children,
        {'properties': {'id': {'pattern': '^MEM-'}}})
    add('recovery', 'memory_recovery', 'read_local', ['parent']+children)
    add('working.parent.read','memory_working','read_local',['parent'],{'properties':{'action':{'enum':['sources','read','pending_actions']}},'required':['action']})
    add('working.parent.write','memory_working','write_local',['parent'],{'properties':{'action':{'enum':['bind','commit']}},'required':['action']})
    add('working.child','memory_working','read_local',children,{'properties':{'action':{'enum':['read','pending_actions']}},'required':['action']})
    return {'version': 1, 'rules': rules}


def isolated_compute_policy():
    from bn_memory.record_metadata import ROLES
    description,properties,required=SCHEMAS['memory_compute']
    schema={'type':'object','properties':copy.deepcopy(properties),'required':list(required),'additionalProperties':False}
    return {'version':1,'rules':[{'id':'memory.compute.isolated','tool':'mcp__context__memory_compute',
        'effect':'read_local','roles':list(ROLES),'arguments_schema':schema}]}


def source_lexical_policy():
    rules=[]
    for name,effect,roles,narrowing in [
        ('memory_sync','write_local',['parent'],{'properties':{'target':{'const':'lexical'}},'required':['target']}),
        ('memory_read','read_local',['collector','analyst','reviewer','G','S','D','parser','computation'],{'properties':{'id':{'pattern':'^SRC-'}}})]:
        _,properties,required=SCHEMAS[name]
        schema={'allOf':[{'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False},narrowing]}
        rules.append({'id':'memory.source_lexical.'+name,'tool':'mcp__context__'+name,'effect':effect,'roles':roles,'arguments_schema':schema})
    return {'version':1,'rules':rules}


def w2_policy():
    rules=[]
    definitions=[('document_catalogue','write_local',['parent']),('document_partition','write_local',['parent']),
        ('document_extract','write_local',['parent']),('document_read','read_local',list(__import__('bn_memory.record_metadata',fromlist=['ROLES']).ROLES)),
        ('document_describe','read_local',list(__import__('bn_memory.record_metadata',fromlist=['ROLES']).ROLES)),
        ('document_status','read_local',list(__import__('bn_memory.record_metadata',fromlist=['ROLES']).ROLES)),
        ('memory_files','read_local',['parent']),('memory_code','read_local',['parent']),('memory_scope','read_local',['parent']),
        ('memory_library','read_local',['parent']),('memory_data','read_local',['parent']),('knowledge_ingest','query_remote',['parent']),('knowledge_query','query_remote',['parent']),
        ('knowledge_manage','query_remote',['parent'])]
    for name,effect,roles in definitions:
        _,properties,required=SCHEMAS[name]
        schema={'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False}
        if name=='memory_library':schema={'allOf':[schema,{'properties':{'action':{'not':{'const':'parse'}}}}]}
        rules.append({'id':'w2.'+name,'tool':'mcp__context__'+name,'effect':effect,'roles':roles,'arguments_schema':schema})
        if name=='memory_library':
            rules.append({'id':'w2.library.parse','tool':'mcp__context__memory_library','effect':'write_local','roles':['parent'],
                'arguments_schema':{'allOf':[{'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False},{'properties':{'action':{'const':'parse'}},'required':['key','request_id']}]}})
    _,properties,required=SCHEMAS['memory_sync']
    rules.append({'id':'w2.projections','tool':'mcp__context__memory_sync','effect':'write_local','roles':['parent'],
                  'arguments_schema':{'allOf':[{'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False},
                                              {'properties':{'target':{'const':'projections'}},'required':['target']}]}})
    return {'version':1,'rules':rules}


def projection_reconciliation_policy():
    _,properties,required=SCHEMAS["memory_sync"]
    return {"version":1,"rules":[{"id":"w2.projection.reconcile","tool":"mcp__context__memory_sync","effect":"write_local","roles":["parent"],"arguments_schema":{"allOf":[{"type":"object","properties":copy.deepcopy(properties),"required":required,"additionalProperties":False},{"properties":{"target":{"const":"reconcile"}},"required":["id","backend"]}]}}]}

def w3_child_policy():
    from bn_memory.record_metadata import ROLES
    rules=[]
    for name in ['memory_files','memory_code','memory_data','memory_library']:
        _,properties,required=SCHEMAS[name]
        schema={'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False}
        if name=='memory_library':schema={'allOf':[schema,{'properties':{'action':{'enum':['item','children','attachment']}},'required':['key']}]}
        if name=='memory_files':schema={'allOf':[schema,{'properties':{'action':{'const':'read'}}}]}
        rules.append({'id':'w3.child.'+name,'tool':'mcp__context__'+name,'effect':'read_local','roles':[r for r in ROLES if r!='parent'],'arguments_schema':schema})
    return {'version':1,'rules':rules}
