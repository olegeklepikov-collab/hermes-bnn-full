"""Configuration inventory, never a claim of live service or semantic acceptance."""
from bn_memory.schemas import SCHEMAS
from bn_memory.backend_policy import BackendPolicy


def inventory(host):
    rows=[]
    for name in sorted(SCHEMAS):
        rules=[rule for rule in host.actions.rules.values() if rule['tool']=='mcp__context__'+name]
        rows.append({'tool':name,'declared':bool(rules),'advertised_by_rpc':name in host.rpc.tools(),
                     'rule_ids':sorted(rule['id'] for rule in rules),
                     'effects':sorted({rule['effect'] for rule in rules}),
                     'roles':sorted({role for rule in rules for role in rule['roles']})})
    try:backends=BackendPolicy(host.config).inventory();backend_error=None
    except ValueError as exc:backends=[];backend_error=str(exc)
    return {'contract':'BNCapabilityInventoryV1','profile_id':host.store.profile,
            'scope':'common-memory interface and its background adapters only',
            'tools':rows,'backends':backends,'backend_policy_error':backend_error,
            'rules_outside_common_interface':[{'id':rule['id'],'tool':rule['tool'],'effect':rule['effect']}
                for rule in host.actions.rules.values() if not rule['tool'].startswith('mcp__context__') or rule['tool'][len('mcp__context__'):] not in SCHEMAS],
            'live_service_verification_performed':False,'configuration_is_not_system_acceptance':True,
            'rpc_requires_exact_final_native_receipt':True,'prepared_signature_grants_execution':False}
