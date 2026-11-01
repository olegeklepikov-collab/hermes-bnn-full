"""Семь составов, внешние процедурные обязательства и доверенное принятие.

Ни одна обязательная процедура не удаляется из плана из-за отсутствия владельца.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
from .common import ROOT, BridgeError, canonical, digest, load, MAX_CONTEXT_BYTES


def route_status(engine):
    terminal = {'pass', 'limited', 'not_applicable'}
    local, external = [], []
    for item in engine.plan:
        p = engine.catalog[item['procedure_id']]
        row = {'procedure_id': p['id'], 'owner': p['owning_component'], 'status': item['status'],
               'mandatory_core': p['mandatory_core'], 'dependencies': p['dependencies'],
               'output_type': p['output_type']}
        (local if p['owning_component'] in engine.components else external).append(row)
    return {'route': ''.join(c for c in 'GSD' if c in engine.components),
            'local_obligations': local, 'external_obligations': external,
            'local_pending': sum(x['status'] not in terminal for x in local),
            'external_pending': sum(x['status'] not in terminal for x in external),
            'foreign_obligations_removed': False,
            'completion': 'Все применимые обязательства и условия close исходного контроллера; локальный состав не равен полному диагностическому исполнению'}


def next_request(engine, context):
    result = engine.next_step()
    if result.get('procedure') is not None or engine.state in ('partial', 'blocked', 'closed', 'degraded'):
        return result
    for item in engine.plan:
        if item['status'] in ('pass', 'limited', 'not_applicable'):
            continue
        p = engine.catalog[item['procedure_id']]
        if p['owning_component'] in engine.components:
            continue
        if any(not engine._accepted(dep, p['id']) for dep in p['dependencies']):
            continue
        manifest = context.manifest(components=p['owning_component'], procedure_ids=[p['id']])
        assembled = context.assemble_context(manifest, byte_limit=MAX_CONTEXT_BYTES)
        missing = [s['collection'] for s in p['input_selectors'] if len(engine.case.get(s['collection'], [])) < s['minimum']]
        return {**result, 'state': 'awaiting_external_product', 'external_request': {
            'procedure': deepcopy(p), 'producer_component': p['owning_component'],
            'case_revision': engine.case['revision'], 'input_fingerprint': engine._fingerprint(p),
            'required_output_type': p['output_type'], 'target_bindings': engine._bindings(p),
            'missing_inputs': missing, 'context_manifest_digest': manifest['digest'],
            'context_text_sha256': assembled['text_sha256'],
            'acceptance': 'Доверенный внешний исполнитель, подписанная квитанция и host-command external-commit',
            'local_components_unchanged': list(engine.components), 'completed': False}}
    return result


def signature(body, key):
    return hmac.new(key, b'GSD-EXTERNAL-PROCEDURE-1\0' + canonical(body), hashlib.sha256).hexdigest()


def verify_receipt(receipt, modules):
    required = {'id', 'producer', 'run_id', 'procedure_id', 'case_revision', 'input_fingerprint',
                'context_manifest_digest', 'context_text_sha256', 'context_delivery_attested',
                'output_digests', 'status', 'postcondition_observed', 'reason', 'cost', 'deadline', 'signature'}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise BridgeError('EXTERNAL_RECEIPT', 'Неполный или расширенный договор внешней квитанции')
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(load(ROOT/'contracts/external_receipt.schema.json')).iter_errors(receipt))
    if errors:
        raise BridgeError('EXTERNAL_RECEIPT', errors[0].message)
    path = os.environ.get('GSD_HOST_POLICY')
    if not path:
        raise BridgeError('HOST_POLICY_REQUIRED', 'Не настроены доверенные внешние исполнители')
    policy = load(Path(path).expanduser().resolve())
    if not isinstance(policy, dict) or policy.get('contract') != 'gsd.host-policy/1':
        raise BridgeError('HOST_POLICY_INVALID', 'Неверный договор политики среды')
    errors = list(Draft202012Validator(load(ROOT/'contracts/host_policy.schema.json')).iter_errors(policy))
    if errors:
        raise BridgeError('HOST_POLICY_INVALID', errors[0].message)
    producer = policy.get('procedure_executors', {}).get(receipt['producer'])
    if not isinstance(producer, dict) or producer.get('enabled') is not True:
        raise BridgeError('EXECUTOR_UNTRUSTED_OR_REVOKED', 'Исполнитель не зарегистрирован или отозван')
    components = producer.get('components')
    if not isinstance(components, list) or not components or not set(components) <= set('GSD'):
        raise BridgeError('HOST_POLICY_INVALID', 'Не определена область исполнителя')
    key_path = Path(producer['key_file']).expanduser()
    if not key_path.is_absolute():
        raise BridgeError('EXECUTOR_KEY', 'Нужен абсолютный путь ключа внешнего исполнителя')
    key_path = key_path.resolve()
    if not key_path.is_file() or (os.name == 'posix' and key_path.stat().st_mode & 0o077):
        raise BridgeError('EXECUTOR_KEY', 'Ключ исполнителя должен быть закрыт от других пользователей')
    key = key_path.read_bytes()
    if len(key) != 32:
        raise BridgeError('EXECUTOR_KEY', 'Требуется отдельный ключ из 32 байт')
    if type(receipt['case_revision']) is not int or receipt['case_revision'] < 0:
        raise BridgeError('EXTERNAL_RECEIPT', 'Редакция должна быть целой')
    for name in ('id', 'producer', 'run_id', 'procedure_id'):
        modules['triad'].require_identifier(receipt[name], name)
    body = {k: v for k, v in receipt.items() if k != 'signature'}
    sig = receipt['signature']
    if not isinstance(sig, str) or not hmac.compare_digest(signature(body, key), sig):
        raise BridgeError('EXTERNAL_SIGNATURE', 'Подпись внешнего исполнения не подтверждена')
    if datetime.now(timezone.utc) >= modules['records'].time_value(receipt['deadline']):
        raise BridgeError('EXTERNAL_EXPIRED', 'Истёк срок внешней квитанции')
    if receipt['context_delivery_attested'] is not True:
        raise BridgeError('CONTEXT_DELIVERY_REQUIRED', 'Поставщик не подтвердил доставку точного контекста')
    return producer


def accept_external(service, receipt):
    """Не публикуется как инструмент модели. Ключ исполнителя задаёт оператор."""
    producer = verify_receipt(receipt, service.modules)
    fp = digest(receipt)
    with service.store.transaction() as con:
        revision, engine = service._restore(con, receipt['run_id'])
        p = engine.catalog.get(receipt['procedure_id'])
        if not p or p['owning_component'] in engine.components or p['owning_component'] not in producer['components']:
            raise BridgeError('EXECUTOR_SCOPE', 'Неверный владелец или внешняя процедура уже входит в локальный состав')
        if receipt['case_revision'] != engine.case['revision'] or receipt['input_fingerprint'] != engine._fingerprint(p):
            raise BridgeError('STALE_EXTERNAL_INPUT', 'Внешний результат относится к другим входам')
        manifest = service.corpus.manifest(components=p['owning_component'], procedure_ids=[p['id']])
        context = service.corpus.assemble_context(manifest, byte_limit=MAX_CONTEXT_BYTES)
        if (receipt['context_manifest_digest'] != manifest['digest'] or receipt['context_text_sha256'] != context['text_sha256']):
            raise BridgeError('STALE_EXTERNAL_CONTEXT', 'Контекст внешнего исполнения не совпадает')
        outputs = receipt['output_digests']
        artifacts = {a['id']: a for a in engine.case['artifacts']}
        if (not isinstance(outputs, dict) or not outputs
            or any(oid not in artifacts or digest(artifacts[oid]) != value for oid, value in outputs.items())):
            raise BridgeError('EXTERNAL_OUTPUT_CHANGED', 'Выходы не зарегистрированы либо изменены')
        # Актуальность и отзыв проверяются ДО подавления повтора.
        prior = service.store.prior(con, 'external.'+receipt['run_id'], receipt['id'], fp)
        if prior is not None:
            return {**prior, 'duplicate': True}
        if any(not engine._accepted(dep, p['id']) for dep in p['dependencies']):
            raise BridgeError('EXTERNAL_DEPENDENCY', 'Зависимости внешней процедуры не приняты')
        if receipt['status'] not in ('pass', 'limited'):
            raise BridgeError('EXTERNAL_STATUS', 'Квитанция принимает только фактически предъявленный pass/limited; пробел остаётся внешним обязательством')
        payload = {'procedure_id': p['id'], 'attempt_id': 'external.'+receipt['id'],
                   'status': receipt['status'], 'output_ids': sorted(outputs),
                   'expected_revision': receipt['case_revision'],
                   'postcondition_observed': receipt['postcondition_observed'],
                   'reason': receipt['reason'], 'cost': receipt['cost']}
        original_components = list(engine.components)
        error = None
        try:
            service.lifecycle.check_commit(con, engine, payload)
            # Тот же исходный commit проверяет тип выхода, отпечатки, зависимости,
            # лимиты и атомарные цели. Область внешнего исполнителя временная,
            # не сохраняется как локальная активация компонента.
            engine.components = [p['owning_component']]
            engine.commit(**payload)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            error = {'code': getattr(exc, 'code', 'EXTERNAL_CONTRACT_REJECTED'), 'message': str(exc)}
        finally:
            engine.components = original_components
        if error is None:
            engine._event({'event': 'external_procedure_accepted', 'receipt_digest': fp,
                           'producer': receipt['producer'], 'procedure_id': p['id'],
                           'context_manifest_digest': manifest['digest'],
                           'semantic_verification': 'producer_attested_not_independently_proven',
                           'local_components': original_components})
        result = service._save(con, receipt['run_id'], engine, revision+1)
        result.update({'operation_accepted': error is None, 'error': error,
                       'external_receipt_digest': fp, 'local_components': original_components})
        service.store.remember(con, 'external.'+receipt['run_id'], receipt['id'], fp, result)
        return result
