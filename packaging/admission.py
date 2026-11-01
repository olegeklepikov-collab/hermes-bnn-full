"""Finite release admission; missing execution never becomes a passing gate."""
from __future__ import annotations

import re

KINDS={'live_model_and_subagents':'live_model','live_Telegram':'live_gateway','end_to_end_research':'live_research'}


def evaluate(required,release,evidence):
    outcomes={};errors=[]
    if not required:errors.append('empty_required_gate_policy')
    for item in evidence:
        if item.get('archive_sha256')!=release['archive']['sha256'] or item.get('source_commit')!=release['source_commit']:
            errors.append('evidence_for_different_program');continue
        for name,value in item.get('gates',{}).items():
            if name not in required:continue
            if name in outcomes and outcomes[name]!=value:
                errors.append('conflicting_evidence:'+name);continue
            if value.get('status')!='passed' or not re.fullmatch(r'[0-9a-f]{64}',str(value.get('witness_sha256',''))):
                outcomes[name]={'status':'not_confirmed'};continue
            if name in KINDS and value.get('execution_kind')!=KINDS[name]:
                outcomes[name]={'status':'wrong_execution_kind'};continue
            outcomes[name]=value
    missing=[name for name in required if outcomes.get(name,{}).get('status')!='passed']
    return {'contract':'BNNReleaseAdmissionV1','archive_sha256':release['archive']['sha256'],'source_commit':release['source_commit'],'eligible_for_production':not missing and not errors,'missing_or_unconfirmed':missing,'errors':errors,'external_human_semantic_review_required':False,'production_deployment_authority_granted':False}
