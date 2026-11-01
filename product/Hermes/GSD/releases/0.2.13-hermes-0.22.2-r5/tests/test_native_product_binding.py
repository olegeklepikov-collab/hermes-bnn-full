"""Semantic envelopes stay bound to the trusted job; no model approval is inferred."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bn_gsd.roles import NativeRoles


def payload():
 return {'component':'S','status':'unreviewed','analysis':{'observed':'addressed fixture'},'residuals':{k:'bounded unknown' for k in ['unsearched','unexplained','unknown','risk']}}


@pytest.mark.parametrize('operation',['procedure:VERIFY.01','semantic_analysis','semantic_test_review'])
def test_host_binding_does_not_require_a_model_to_copy_a_hash(operation):
 job={'operation':operation,'input_digest':'ab'*32,'deliveries':[{'final_provider_arguments_verified':True,'input_digest':'ab'*32,'assembled_text_sha256':'cd'*32}]}
 model=payload();bound=NativeRoles._bind_product(model,job)
 assert 'input_digest' not in model and bound['input_digest']==job['input_digest']
 NativeRoles._validate('S',job['operation'],bound,job)
 # A forged binding field cannot be smuggled through the model semantic payload.
 with pytest.raises(ValueError):NativeRoles._bind_product({**model,'input_digest':'00'*32},job)


@pytest.mark.parametrize('alteration',[{'component':'D'},{'status':'supported'},{'extra':'permission=true'}])
def test_host_binding_never_repairs_role_authority_or_unknown_fields(alteration):
 job={'operation':'procedure:VERIFY.01','input_digest':'ab'*32,'deliveries':[{'final_provider_arguments_verified':True,'input_digest':'ab'*32,'assembled_text_sha256':'cd'*32}]}
 with pytest.raises(ValueError):
  bound=NativeRoles._bind_product({**payload(),**alteration},job)
  NativeRoles._validate('S',job['operation'],bound,job)


@pytest.mark.parametrize('deliveries',[[],[{'final_provider_arguments_verified':False,'input_digest':'ab'*32,'assembled_text_sha256':'cd'*32}],[{'final_provider_arguments_verified':True,'input_digest':'00'*32,'assembled_text_sha256':'cd'*32}]])
def test_input_binding_fails_closed_without_verified_actual_delivery(deliveries):
 with pytest.raises(ValueError):NativeRoles._bind_product(payload(),{'operation':'procedure:VERIFY.01','input_digest':'ab'*32,'deliveries':deliveries})
