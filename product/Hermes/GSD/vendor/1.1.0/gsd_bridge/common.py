"""Строгий JSON, контроль состава и загрузка единственного ядра."""
from __future__ import annotations
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'
MAX_JSON_BYTES = 24 * 1024 * 1024
MAX_CONTEXT_BYTES = 8 * 1024 * 1024

class BridgeError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def read_json(data: str | bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BridgeError('INVALID_JSON', 'Повтор ключа JSON: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise BridgeError('INVALID_JSON', 'Недопустимое число: ' + value)
    raw = data.encode('utf-8') if isinstance(data, str) else data
    if len(raw) > MAX_JSON_BYTES:
        raise BridgeError('INPUT_TOO_LARGE', 'Превышен предел входного JSON')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise BridgeError('INVALID_JSON', str(exc)) from exc

def load(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise BridgeError('INPUT_TOO_LARGE', 'Файл превышает предел JSON')
    return read_json(path.read_bytes())

def object_input(value: Any, name: str = 'arguments') -> dict:
    if not isinstance(value, dict):
        raise BridgeError('INVALID_INPUT', name + ': требуется объект JSON')
    canonical(value)
    return value

def verify_tree(root: Path, manifest_name: str = 'manifest.json') -> dict:
    root = root.resolve()
    manifest = load(root / manifest_name)
    issues, seen = [], set()
    for row in manifest['files']:
        rel = row['path']
        if rel in seen:
            issues.append({'path': rel, 'reason': 'duplicate_manifest_path'})
            continue
        seen.add(rel)
        path = root / rel
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            issues.append({'path': rel, 'reason': 'missing_or_unsafe'})
            continue
        raw = path.read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            issues.append({'path': rel, 'reason': 'content_mismatch'})
    # Проверка полного списка, а не только перечисленных файлов.
    ignored = {manifest_name, 'SHA256SUMS'}
    unexpected = []
    for path in root.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            rel = path.relative_to(root).as_posix()
            if rel not in seen and rel not in ignored:
                unexpected.append(rel)
    return {'valid': not issues and not unexpected, 'checked_files': len(seen),
            'issues': issues, 'unexpected_files': sorted(unexpected),
            'authenticity_proven': False}

_loaded = None

def engine_modules():
    """Вызывать только в отдельном процессе интеграции, не в процессе Hermes."""
    global _loaded
    if _loaded is not None:
        return _loaded
    check = verify_tree(ENGINE)
    if not check['valid']:
        raise BridgeError('ENGINE_INTEGRITY', json.dumps(check, ensure_ascii=False))
    tools = (ENGINE / 'tools').resolve()
    for name in ('_base', 'records', 'corpus', 'engine', 'triad'):
        existing = sys.modules.get(name)
        if existing is not None:
            path = Path(getattr(existing, '__file__', '')).resolve()
            if not path.is_relative_to(tools):
                raise BridgeError('IMPORT_CONFLICT', 'В процессе уже загружен иной модуль ' + name)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(tools))
    _loaded = {name: importlib.import_module(name)
               for name in ('_base', 'records', 'corpus', 'engine', 'triad')}
    return _loaded

def state_path() -> Path:
    value = os.environ.get('GSD_STATE_DIR')
    if not value:
        raise BridgeError('STATE_NOT_CONFIGURED', 'Задайте GSD_STATE_DIR вне каталога поставки')
    path = Path(value).expanduser().resolve()
    if path == ROOT or path.is_relative_to(ROOT):
        raise BridgeError('STATE_IN_PACKAGE', 'Рабочее состояние должно находиться вне поставки')
    return path
