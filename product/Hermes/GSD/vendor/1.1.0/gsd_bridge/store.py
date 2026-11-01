"""Локальное хранилище: транзакции, проверка редакции и подписанные снимки.
Не является защитой от администратора ОС, подмены ключа или отката всей базы.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import hmac
import os
import sqlite3
from pathlib import Path
from typing import Any
from .common import BridgeError, canonical, read_json, state_path, MAX_JSON_BYTES

class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or state_path()
        raw_key = os.environ.get('GSD_TRUST_KEY_FILE')
        if not raw_key:
            raise BridgeError('TRUST_KEY_NOT_CONFIGURED', 'Задайте GSD_TRUST_KEY_FILE')
        key_path = Path(raw_key).expanduser().resolve()
        if not key_path.is_file() or key_path.is_relative_to(self.directory):
            raise BridgeError('TRUST_KEY_INVALID', 'Ключ должен существовать вне каталога состояния')
        if os.name == 'posix' and key_path.stat().st_mode & 0o077:
            raise BridgeError('TRUST_KEY_PERMISSIONS', 'Ключ должен быть доступен только владельцу: chmod 600')
        self.key = key_path.read_bytes()
        if len(self.key) != 32:
            raise BridgeError('TRUST_KEY_INVALID', 'Требуется ровно 32 байта случайного ключа')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == 'posix' and self.directory.stat().st_mode & 0o077:
            raise BridgeError('STATE_PERMISSIONS', 'Каталог состояния должен иметь права 700')
        self.db_path = self.directory / 'state.sqlite3'
        if self.db_path.is_symlink():
            raise BridgeError('STATE_PATH_INVALID', 'Символическая ссылка на базу не допускается')
        con = self.connect()
        try:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    payload BLOB NOT NULL, mac TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    scope TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload BLOB NOT NULL, mac TEXT NOT NULL,
                    PRIMARY KEY (scope, request_id));
            ''')
        finally:
            con.close()
        if os.name == 'posix':
            os.chmod(self.db_path, 0o600)

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        con.execute('PRAGMA journal_mode=DELETE')
        con.execute('PRAGMA synchronous=FULL')
        con.execute('PRAGMA busy_timeout=30000')
        return con

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _mac(self, context: list, raw: bytes) -> str:
        return hmac.new(self.key, canonical(context) + b'\x00' + raw, hashlib.sha256).hexdigest()

    def get(self, con, identifier: str) -> tuple[int, Any]:
        row = con.execute('SELECT revision,payload,mac FROM records WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise BridgeError('NOT_FOUND', 'Запись не найдена')
        revision, raw, mac = row
        if not hmac.compare_digest(mac, self._mac(['record', identifier, revision], raw)):
            raise BridgeError('STATE_INTEGRITY', 'Снимок не соответствует доверенному ключу')
        return revision, read_json(raw)

    def put(self, con, identifier: str, value: Any, revision: int):
        raw = canonical(value)
        if len(raw) > MAX_JSON_BYTES:
            raise BridgeError('STATE_SIZE_LIMIT', 'Снимок превышает предел одной записи')
        con.execute('INSERT INTO records(id,revision,payload,mac) VALUES(?,?,?,?) '
                    'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,'
                    'payload=excluded.payload,mac=excluded.mac',
                    (identifier, revision, raw, self._mac(['record', identifier, revision], raw)))

    def prior(self, con, scope: str, request_id: str, fingerprint: str):
        row = con.execute('SELECT fingerprint,payload,mac FROM requests WHERE scope=? AND request_id=?',
                          (scope, request_id)).fetchone()
        if row is None:
            return None
        fp, raw, mac = row
        if not hmac.compare_digest(mac, self._mac(['request', scope, request_id, fp], raw)):
            raise BridgeError('STATE_INTEGRITY', 'Повреждена запись повторного запроса')
        if fp != fingerprint:
            raise BridgeError('IDEMPOTENCY_CONFLICT', 'Один request_id использован для разных входов')
        return read_json(raw)

    def remember(self, con, scope: str, request_id: str, fingerprint: str, result: Any):
        raw = canonical(result)
        if len(raw) > MAX_JSON_BYTES:
            raise BridgeError('STATE_SIZE_LIMIT', 'Результат превышает предел сохранения')
        con.execute('INSERT INTO requests VALUES(?,?,?,?,?)',
                    (scope, request_id, fingerprint, raw,
                     self._mac(['request', scope, request_id, fingerprint], raw)))

    def complete(self, con, scope: str, request_id: str, fingerprint: str, result: Any):
        previous = self.prior(con, scope, request_id, fingerprint)
        if previous is None or previous.get('effective_status') != 'in_progress_or_outcome_unknown':
            raise BridgeError('REQUEST_STATE', 'Нет зарезервированного запроса для завершения')
        raw = canonical(result)
        if len(raw) > MAX_JSON_BYTES:
            raise BridgeError('STATE_SIZE_LIMIT', 'Результат превышает предел сохранения')
        con.execute('UPDATE requests SET payload=?,mac=? WHERE scope=? AND request_id=?',
                    (raw, self._mac(['request',scope,request_id,fingerprint],raw),scope,request_id))
