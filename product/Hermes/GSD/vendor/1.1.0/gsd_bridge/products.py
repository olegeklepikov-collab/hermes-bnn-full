"""Версионированная оболочка продукта; содержание и статус не повышаются.

Зарегистрированный продукт не является доказательством своего содержания.
"""
from __future__ import annotations
from copy import deepcopy
from .common import BridgeError, canonical, digest


def source_status(product):
    top = product.get('status')
    epistemic = product.get('M')
    nested = epistemic.get('epistemic_status') if isinstance(epistemic, dict) else None
    for value in (top, nested):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise BridgeError('PRODUCT_STATUS', 'Статус должен быть типизированной непустой строкой')
    if top and nested and top != nested:
        raise BridgeError('PRODUCT_STATUS', 'Два расходящихся собственных статуса')
    return top or nested or 'unreviewed'


class ProductRegistry:
    def __init__(self, store, triad):
        self.store, self.triad = store, triad

    def register(self, *, namespace, logical_key, product, input_objects, origin_component,
                 origin_ref, expected_version, request_id):
        if not isinstance(product, dict) or not product:
            raise BridgeError('PRODUCT_INPUT', 'Нужен непустой исходный продукт')
        if not isinstance(input_objects, dict):
            raise BridgeError('PRODUCT_INPUT', 'Входы должны быть адресным отображением')
        if type(expected_version) is not int or expected_version < 0:
            raise BridgeError('PRODUCT_VERSION', 'Ожидаемая версия: неотрицательное целое')
        for name, value in [('namespace', namespace), ('logical_key', logical_key), ('origin_ref', origin_ref), ('request_id', request_id)]:
            self.triad.require_identifier(value, name)
        if origin_component not in ('G', 'S', 'D'):
            raise BridgeError('PRODUCT_ORIGIN', 'Неизвестный компонент происхождения')
        for key in input_objects:
            self.triad.require_identifier(key, 'input_id')
        identifier = 'PRODUCT.' + digest([namespace, logical_key])
        body = {'type': 'RegisteredProduct', 'status': source_status(product),
                'product': deepcopy(product), 'product_digest': digest(product),
                'input_bindings': {key: digest(value) for key, value in sorted(input_objects.items())},
                'origin': {'component': origin_component, 'reference': origin_ref,
                           'attestation': 'declared_by_caller_not_independent_verification'},
                'namespace': namespace, 'logical_key': logical_key}
        fp = digest([body, expected_version])
        with self.store.transaction() as con:
            prior = self.store.prior(con, 'register.'+identifier, request_id, fp)
            if prior is not None:
                return {**prior, 'duplicate': True}
            try:
                old_revision, old = self.store.get(con, identifier)
            except BridgeError as exc:
                if exc.code != 'NOT_FOUND':
                    raise
                old_revision, old = 0, None
            if old is not None and old['content_digest'] == digest(body):
                result = {'product': old['current'], 'duplicate': True, 'epistemic_promotion': False}
            else:
                if expected_version != old_revision:
                    raise BridgeError('STALE_PRODUCT_VERSION', 'Редакция продукта изменилась')
                version = old_revision+1
                current = {'id': identifier, 'version': version, **body}
                history = deepcopy(old['history']) if old else []
                if old:
                    history.append(old['current'])
                self.store.put(con, identifier, {'kind': 'registered_product', 'current': current,
                    'history': history, 'content_digest': digest(body)}, version)
                result = {'product': current, 'duplicate': False, 'epistemic_promotion': False}
            self.store.remember(con, 'register.'+identifier, request_id, fp, result)
            return result

    def get(self, identifier, version=None, *, current_required=True):
        if version is not None and (type(version) is not int or version < 1):
            raise BridgeError('PRODUCT_VERSION', 'Версия должна быть положительным целым')
        if type(current_required) is not bool:
            raise BridgeError('PRODUCT_VERSION', 'current_required должен быть bool')
        with self.store.transaction() as con:
            revision, record = self.store.get(con, identifier)
            if record.get('kind') != 'registered_product':
                raise BridgeError('PRODUCT_TYPE', 'Это не зарегистрированный продукт')
            if version is None or version == revision:
                return deepcopy(record['current'])
            if current_required:
                raise BridgeError('STALE_PRODUCT_VERSION', 'Указанная версия уже не является текущей')
            for old in record['history']:
                if old['version'] == version:
                    return deepcopy(old)
            raise BridgeError('NOT_FOUND', 'Версия продукта не найдена')

    def prepare_handoff(self, *, product_id, product_version, header, input_objects, context, standard):
        payload = self.get(product_id, product_version)
        if not isinstance(input_objects, dict) or not isinstance(header, dict):
            raise BridgeError('HANDOFF_INPUT', 'Нужны объекты заголовка и зависимостей')
        bindings = {key: digest(value) for key, value in sorted(input_objects.items())}
        if bindings != payload['input_bindings']:
            raise BridgeError('STALE_PRODUCT_INPUT', 'Передача требует тех же фактических входов, что регистрация')
        if set(input_objects) & {'context', 'standard', product_id}:
            raise BridgeError('HANDOFF_RESERVED_ID', 'Идентификатор входа пересекается с обязательными полями передачи')
        fields = {'id', 'receiver', 'component_versions', 'corpus_digest', 'risk_floor',
                  'deadline', 'budget_reservation', 'budget_amount', 'residuals'}
        if set(header) != fields:
            raise BridgeError('HANDOFF_HEADER', 'Укажите только поля маршрута, ресурса, срока и остатка')
        message = {**deepcopy(header), 'sender': payload['origin']['component'], 'protocol_version': '3.0',
                   'payload_id': product_id, 'payload_version': product_version, 'payload_digest': digest(payload),
                   'dependency_bindings': bindings, 'context_digest': digest(context), 'standard_digest': digest(standard),
                   'allowed_effects': ['local_analysis'], 'input_status': payload['status']}
        self.triad.validate_handoff_header(message)
        if source_status(payload['product']) != payload['status'] or digest(payload['product']) != payload['product_digest']:
            raise BridgeError('PRODUCT_INTEGRITY', 'Статус или содержание оболочки расходятся с источником')
        return {'message': message, 'objects': {**deepcopy(input_objects), 'context': deepcopy(context),
                    'standard': deepcopy(standard), product_id: payload},
                'delivery_performed': False, 'budget_reserved': False,
                'next_required': 'ProductRegistry.deliver с фактическим HandoffChannel и бюджетом принимающей среды'}

    def deliver(self, *, channel, receiver, now=None, **arguments):
        """Локальный программный приём. channel и бюджет передаёт доверенная среда.

        Сетевой транспорт и долговременное подавление доставки — обязанность хоста.
        """
        prepared = self.prepare_handoff(**arguments)
        receipt = channel.send(prepared['message'], objects=prepared['objects'], receiver=receiver, now=now)
        return {'receipt': receipt, 'registered_product': prepared['objects'][arguments['product_id']],
                'delivery': 'local_acceptance_for_processing', 'semantic_execution_performed': False,
                'external_effect_performed': False}
