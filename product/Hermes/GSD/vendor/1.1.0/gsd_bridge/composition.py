"""Композиция исходных операций с проверкой зависимостей до вызова.

engine/ не изменяется. Результат операции, попытка вызова и исполнение
содержательной генерации учитываются раздельно. Отсутствующий G не стирает вход.
"""
from __future__ import annotations
from copy import deepcopy
from .common import BridgeError, digest


def execute_components(triad, active, request, *, generation_provider=None, budget=None):
    active = set(active)
    if not active or not active <= triad.COMPONENTS:
        raise BridgeError('INVALID_COMPONENTS', 'Нужен непустой состав G/S/D')
    policy = request.get('generation_unavailable_policy', 'block_dependents')
    if policy not in ('block_dependents', 'use_supplied_candidates'):
        raise BridgeError('INVALID_FALLBACK_POLICY', 'Неизвестная политика отсутствующего G')
    route = triad.choose_profile(request.get('requested_profile', 'eMVP'),
                                request.get('risk', {k: None for k in triad.RISK_KEYS}))
    limits = request.get('execution_budget', {'step_limit': 100, 'reserve_steps': 1})
    budget = budget or triad.SharedBudget(limits['step_limit'], limits['reserve_steps'])
    result = {'profile': route, 'protocol_version': triad.PROTOCOL,
              'active_components': sorted(active), 'invoked_components': [],
              'executed_components': [], 'semantic_generation_performed': False,
              'outputs': {}, 'open_obligations': [], 'blocked_components': [],
              'input_candidates': deepcopy(request.get('candidates', [])),
              'candidate_provenance': [], 'branch': 'requested_composition'}
    candidates = deepcopy(request.get('candidates', []))
    if not isinstance(candidates, list):
        raise BridgeError('INVALID_INPUT', 'candidates должен быть списком')
    review = request.get('review')
    observations = request.get('observations', [])
    if not isinstance(observations, list):
        raise BridgeError('INVALID_INPUT', 'observations должен быть списком')

    def invoke(component, units, fn):
        key = component + '.' + digest(request)
        if not budget.allocate(key, units):
            raise BridgeError('ALREADY_EXECUTED', 'Операция уже учтена; используйте сохранённый результат')
        result['invoked_components'].append(component)
        value = fn()
        actual = value.get('resource', {}).get('attempted', units) if component == 'G' else units
        budget.settle(key, actual)
        result['outputs'][component] = value
        return value

    def blocked(component, dependencies):
        result['blocked_components'].append(component)
        result['outputs'][component] = {'component': component, 'status': 'awaiting_dependency',
            'missing': dependencies, 'invoked': False, 'action_authorized': False}

    if active == {'S'} and request.get('operation') in ('derive', 'principle_contract'):
        units = max(1, len(request.get('premises', [])) + len(request.get('implications', [])))
        invoke('S', units, lambda: triad.StrictComponent().derive(request['premises'], request['implications'], scope=request['scope'])
               if request['operation'] == 'derive' else triad.StrictComponent().principle_contract(request['proposal']))
        result['executed_components'].append('S')
    else:
        missing_g = False
        if 'G' in active:
            gen = request['generation']
            # Даже интерфейс без поставщика валидирует запрос, но не расходует
            # резерв смыслового поиска и не объявляется исполненным G.
            if gen.get('method') == 'agent' and generation_provider is None:
                result['invoked_components'].append('G')
                g = triad.GenerationComponent().run(gen, provider=None)
                result['outputs']['G'] = g
            else:
                g = invoke('G', gen['scan_budget'],
                           lambda: triad.GenerationComponent().run(gen, provider=generation_provider))
            missing_g = g.get('status') in ('awaiting_provider', 'awaiting_dependency')
            if missing_g:
                result['open_obligations'].append({'component': 'G', 'status': g['status'],
                                                  'request_digest': digest(gen)})
                if policy == 'use_supplied_candidates' and candidates:
                    for candidate in candidates:
                        triad.validate_candidate(candidate)
                        if candidate['scope'] != request['scope']:
                            raise BridgeError('SCOPE_MISMATCH', 'Предоставленный кандидат относится к другому C')
                    result['branch'] = 'explicit_supplied_candidates_without_G'
                else:
                    for component in ('S', 'D'):
                        if component in active:
                            blocked(component, ['G'])
            else:
                result['executed_components'].append('G')
                result['semantic_generation_performed'] = gen.get('method') != 'supplied'
                candidates = deepcopy(g['candidates'] + g.get('reused_candidates', []))
        result['candidate_field'] = deepcopy(candidates)
        reused = {c['id'] for c in result['outputs'].get('G', {}).get('reused_candidates', [])}
        for candidate in candidates:
            result['candidate_provenance'].append({'id': candidate.get('id'), 'version': candidate.get('version'),
                'digest': digest(candidate), 'source': 'request.candidates' if missing_g or 'G' not in active
                else ('G.reused_candidates' if candidate.get('id') in reused else 'G.candidates')})
        if 'S' in active and 'S' not in result['blocked_components']:
            if not candidates:
                blocked('S', ['nonempty_candidate_field'])
            else:
                units = max(1, len(candidates) * len(observations))
                review = invoke('S', units,
                    lambda: triad.StrictComponent().compare(candidates, observations, scope=request['scope']))
                result['executed_components'].append('S')
        if 'D' in active and 'D' not in result['blocked_components']:
            dependencies = ([] if candidates else ['nonempty_candidate_field'])
            if 'S' in result['blocked_components'] or review is None:
                dependencies.append('current_comparison_review')
            if dependencies:
                blocked('D', dependencies)
            else:
                # Предметный валидатор исходного D проверяет версии и C до сравнения.
                d = invoke('D', max(1, len(candidates) * (len(candidates)-1)//2),
                    lambda: triad.DiagnosticComponent().run(candidates=candidates, observations=observations,
                        scope=request['scope'], review=review, question=request['question']))
                if not d.get('missing') and d.get('status') not in ('partial', 'awaiting_dependency'):
                    result['executed_components'].append('D')
                else:
                    result['open_obligations'].append({'component': 'D', 'status': d.get('status'),
                                                       'missing': d.get('missing', [])})
    result['resource'] = {'spent_local_units': budget.spent, 'reserve_steps': budget.reserve,
                         'measure': 'Ограниченные локальные операции; не токены и не денежная стоимость'}
    result['unmet_profile_obligations'] = (['Независимая предметная проверка и эксплуатационный допуск не выполнены']
        if triad.PROFILES.index(route['selected']) >= 4 else [])
    return result
