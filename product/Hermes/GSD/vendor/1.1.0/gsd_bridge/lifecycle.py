"""Реестр случаев, проверенное восстановление и общий расход семьи запусков.

Один локальный SQLite и один домен доверия. Не распределённый бюджет Hermes.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import math
import uuid
from .common import ROOT, BridgeError, digest

FORMAT = 'gsd.integration.snapshot/1.1'


class Lifecycle:
    def __init__(self, modules, store, engine_manifest):
        self.modules, self.store, self.engine_manifest = modules, store, engine_manifest

    @staticmethod
    def family_id(case_id):
        return 'case-family.' + digest(case_id)

    def _family(self, con, case_id):
        return self.store.get(con, self.family_id(case_id))

    def _ensure_new_input(self, case):
        if not isinstance(case, dict):
            raise BridgeError('INVALID_INPUT', 'case должен быть объектом')
        self.modules['triad'].require_identifier(case['case_id'], 'case_id')
        if case['contract']['intended_use'] != 'analysis_only':
            raise BridgeError('ANALYSIS_ONLY', 'Доступен только аналитический случай')
        if case['status'] not in ('active', 'partial', 'blocked'):
            raise BridgeError('RESTORE_REQUIRED', 'Завершённое или деградированное состояние нельзя создать заново')
        if case.get('procedure_runs'):
            raise BridgeError('RESTORE_REQUIRED', 'История исполнения принимается только через проверенное восстановление')

    def _find_family(self, con, case_id):
        try:
            return self._family(con, case_id)
        except BridgeError as exc:
            if exc.code != 'NOT_FOUND':
                raise
        # Старые состояния без индекса нельзя обойти новым request_id.
        for (identifier,) in con.execute('SELECT id FROM records'):
            _, value = self.store.get(con, identifier)
            if isinstance(value, dict) and value.get('case', {}).get('case_id') == case_id:
                raise BridgeError('STATE_MIGRATION_REQUIRED', 'Есть прежний запуск без индекса; требуется явная миграция')
        return None

    def create(self, case, triggers, components, request_id, fingerprint):
        self._ensure_new_input(case)
        with self.store.transaction() as con:
            prior = self.store.prior(con, 'case_create', request_id, fingerprint)
            if prior is not None:
                return {**prior, 'duplicate': True}
            existing = self._find_family(con, case['case_id'])
            if existing is not None:
                raise BridgeError('CASE_ALREADY_EXISTS', 'Случай уже зарегистрирован; используйте run_id=' + existing[1]['current_run_id'])
            engine = self.modules['engine'].ProcedureEngine(case, triggers, components=components)
            run_id = str(uuid.uuid4())
            family = {'kind': 'case_family', 'case_id': case['case_id'], 'current_run_id': run_id,
                      'run_ids': [run_id], 'budget': deepcopy(case['contract']['budget']),
                      'spent_steps': 0, 'spent_cost': 0.0, 'usage': {}, 'events': []}
            self.store.put(con, self.family_id(case['case_id']), family, 0)
            result = self.save(con, run_id, engine, 0)
            self.store.remember(con, 'case_create', request_id, fingerprint, result)
            return result

    def restore(self, con, run_id):
        revision, value = self.store.get(con, run_id)
        if value.get('format') != FORMAT:
            raise BridgeError('STATE_MIGRATION_REQUIRED', 'Схема снимка требует явной миграции')
        if value.get('engine_manifest') != self.engine_manifest:
            raise BridgeError('ENGINE_CHANGED', 'Для другого исходного ядра нужна отдельная миграция')
        snap = value['snapshot']
        engine = self.modules['engine'].ProcedureEngine.restore(value['case'], snap,
            trusted_tail=snap['events'][-1]['hash'])
        _, family = self._family(con, engine.case['case_id'])
        if run_id not in family['run_ids']:
            raise BridgeError('STATE_INTEGRITY', 'Запуск отсутствует в доверенном реестре случая')
        usage = family['usage'].get(run_id)
        if not usage or usage != {'steps': engine.spent_steps, 'cost': engine.spent_cost}:
            raise BridgeError('STATE_INTEGRITY', 'Расход снимка расходится с реестром семьи запусков')
        return revision, engine

    def save(self, con, run_id, engine, revision):
        frev, family = self._family(con, engine.case['case_id'])
        if run_id not in family['run_ids']:
            raise BridgeError('STATE_INTEGRITY', 'Незарегистрированный запуск')
        previous = family['usage'].get(run_id, {'steps': 0, 'cost': 0.0})
        ds, dc = engine.spent_steps - previous['steps'], engine.spent_cost - previous['cost']
        if ds < 0 or dc < 0:
            raise BridgeError('BUDGET_ROLLBACK', 'Накопленный расход не обнуляется')
        family['spent_steps'] += ds
        family['spent_cost'] += dc
        family['usage'][run_id] = {'steps': engine.spent_steps, 'cost': engine.spent_cost}
        self.store.put(con, self.family_id(engine.case['case_id']), family, frev+1)
        snap = engine.snapshot()
        self.store.put(con, run_id, {'format': FORMAT, 'case': engine.case, 'snapshot': snap,
            'engine_manifest': self.engine_manifest, 'family_id': self.family_id(engine.case['case_id'])}, revision)
        return {'run_id': run_id, 'store_revision': revision, 'case_revision': engine.case['revision'],
                'state': engine.state, 'trusted_tail': snap['events'][-1]['hash'],
                'spent_steps': engine.spent_steps, 'spent_cost': engine.spent_cost,
                'family_spent_steps': family['spent_steps'], 'family_spent_cost': family['spent_cost'],
                'budget_scope': self.family_id(engine.case['case_id']), 'duplicate': False}

    def check_commit(self, con, engine, payload):
        if payload.get('attempt_id') in engine._attempts:
            return
        cost = payload.get('cost', 0.0)
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
            raise BridgeError('INVALID_COST', 'Нужен конечный неотрицательный расход')
        _, family = self._family(con, engine.case['case_id'])
        b = family['budget']
        if (family['spent_steps'] + 1 > b['step_limit'] - b['reserve_steps']
            or family['spent_cost'] + cost > b['cost_limit']
            or datetime.now(timezone.utc) >= self.modules['records'].time_value(b['deadline'])):
            if engine.state != 'closed':
                engine.stop('Исчерпан общий бюджет семьи запусков')
            raise BridgeError('FAMILY_BUDGET_EXHAUSTED', 'Новый запуск не создаёт новый ресурс случая')

    def family_status(self, con, engine):
        _, family = self._family(con, engine.case['case_id'])
        return {k: deepcopy(family[k]) for k in ('case_id', 'current_run_id', 'run_ids', 'spent_steps', 'spent_cost', 'budget')}

    def new_run_by_host(self, *, case, triggers, components, previous_run_id,
                        expected_store_revision, reason, request_id):
        if not isinstance(reason, str) or not reason.strip():
            raise BridgeError('REASON_REQUIRED', 'Нужно основание отдельного запуска')
        self._ensure_new_input(case)
        fp = digest([case, triggers, components, previous_run_id, expected_store_revision, reason])
        with self.store.transaction() as con:
            prior = self.store.prior(con, 'host_new_run', request_id, fp)
            if prior is not None:
                return {**prior, 'duplicate': True}
            rev, previous = self.restore(con, previous_run_id)
            frev, family = self._family(con, previous.case['case_id'])
            if rev != expected_store_revision or family['current_run_id'] != previous_run_id:
                raise BridgeError('STALE_REVISION', 'Предшествующий запуск или редакция изменились')
            if case['case_id'] != previous.case['case_id'] or case['contract']['budget'] != family['budget']:
                raise BridgeError('BUDGET_SCOPE_CHANGED', 'Новый запуск наследует идентичность случая и область ресурса')
            self.check_commit(con, previous, {})
            if previous.state not in ('closed', 'partial', 'blocked', 'degraded'):
                previous.stop('Создан отдельный запуск по решению оператора: ' + reason)
                self.save(con, previous_run_id, previous, rev+1)
                frev, family = self._family(con, case['case_id'])
            engine = self.modules['engine'].ProcedureEngine(case, triggers, components=components)
            run_id = str(uuid.uuid4())
            engine._event({'event': 'new_run_authorized_by_host', 'previous_run_id': previous_run_id, 'reason': reason,
                           'budget_scope': self.family_id(case['case_id'])})
            family['run_ids'].append(run_id)
            family['current_run_id'] = run_id
            family['events'].append({'event': 'new_run', 'run_id': run_id, 'previous_run_id': previous_run_id, 'reason': reason})
            self.store.put(con, self.family_id(case['case_id']), family, frev+1)
            result = self.save(con, run_id, engine, 0)
            self.store.remember(con, 'host_new_run', request_id, fp, result)
            return result

    def migrate_by_host(self, *, backup_path, apply=False):
        """Только исходные подписанные снимки 1.0.0. Неоднозначные семьи не угадываются."""
        from pathlib import Path
        import sqlite3
        backup = Path(backup_path).expanduser().resolve()
        if backup.exists() or backup.is_relative_to(self.store.directory) or backup.is_relative_to(ROOT):
            raise BridgeError('BACKUP_PATH', 'Нужен новый резервный файл вне каталога состояния')
        candidates = []
        with self.store.transaction() as con:
            by_case = {}
            for (identifier,) in con.execute('SELECT id FROM records'):
                rev, value = self.store.get(con, identifier)
                if not isinstance(value, dict) or 'engine_manifest' not in value or 'snapshot' not in value:
                    continue
                if value.get('format') == FORMAT:
                    continue
                if value['engine_manifest'] != self.engine_manifest:
                    raise BridgeError('ENGINE_CHANGED', 'Миграция другого исходного ядра не поддержана')
                snap = value['snapshot']
                engine = self.modules['engine'].ProcedureEngine.restore(value['case'], snap,
                    trusted_tail=snap['events'][-1]['hash'])
                case_id = engine.case['case_id']
                if case_id in by_case or self._record_exists(con, self.family_id(case_id)):
                    raise BridgeError('AMBIGUOUS_CASE_HISTORY', 'Несколько запусков случая требуют отдельного сверенного переноса')
                by_case[case_id] = identifier
                candidates.append((identifier, rev, value, engine))
            plan = {'migration': '1.0.0_to_1.1.0', 'runs': [x[0] for x in candidates],
                    'applied': False, 'counter_reset': False}
            if not apply:
                return plan
            # Отдельное чтение фиксирует исходную БД до первой записи. Внешние
            # писатели заблокированы BEGIN IMMEDIATE текущей транзакции.
            backup.parent.mkdir(parents=True, exist_ok=True)
            import os
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            source = self.store.connect()
            try:
                destination = sqlite3.connect(backup)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()
            backup.chmod(0o600)
            for run_id, revision, value, engine in candidates:
                family = {'kind': 'case_family', 'case_id': engine.case['case_id'], 'current_run_id': run_id,
                    'run_ids': [run_id], 'budget': deepcopy(engine.case['contract']['budget']),
                    'spent_steps': engine.spent_steps, 'spent_cost': engine.spent_cost,
                    'usage': {run_id: {'steps': engine.spent_steps, 'cost': engine.spent_cost}},
                    'events': [{'event': 'migrated_without_counter_reset'}]}
                self.store.put(con, self.family_id(engine.case['case_id']), family, 0)
                # Сохраняется ТОТ ЖЕ исходный снимок, а не новый конструктор.
                self.store.put(con, run_id, {**value, 'format': FORMAT,
                    'family_id': self.family_id(engine.case['case_id'])}, revision+1)
            return {**plan, 'applied': True, 'backup_path': str(backup)}

    def _record_exists(self, con, identifier):
        try:
            self.store.get(con, identifier)
            return True
        except BridgeError as exc:
            if exc.code == 'NOT_FOUND':
                return False
            raise
