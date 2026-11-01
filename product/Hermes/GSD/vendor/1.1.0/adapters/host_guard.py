"""Обязательная точка допуска для встраивания в фактический диспетчер хоста.
Наличие этого файла не подключает защиту к чужим инструментам автоматически.
"""
from __future__ import annotations
from typing import Callable, Any
from copy import deepcopy
import hashlib
import json

def request_digest(tool: str, arguments: dict) -> str:
    raw=json.dumps({'tool':tool,'arguments':arguments},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

class BlockedAction(RuntimeError):
    pass

class GuardedDispatcher:
    """Проверка допуска непосредственно перед вызовом, с отказом при ошибке.

    authorize — доверенная функция хоста. Она не должна принимать разрешение
    из текста модели. dispatch должен быть единственным путём к реальному эффекту.
    """
    def __init__(self, authorize: Callable[[str,dict],dict], dispatch: Callable[[str,dict],Any]):
        self.authorize=authorize
        self.dispatch=dispatch

    def __call__(self, tool: str, arguments: dict):
        if not isinstance(tool,str) or not tool.strip() or not isinstance(arguments,dict):
            raise BlockedAction('Некорректный запрос к исполнителю')
        frozen=deepcopy(arguments)
        fingerprint=request_digest(tool,frozen)
        try:
            decision=self.authorize(tool,deepcopy(frozen))
        except Exception as exc:
            raise BlockedAction('Обязательная проверка не завершена; действие не исполнено') from exc
        if not isinstance(decision,dict) or decision.get('allow') is not True or decision.get('request_digest') != fingerprint:
            raise BlockedAction('Нет действующего разрешения на точные параметры действия')
        # Проверка изменения параметров и внешних условий должна быть атомарна
        # с исполнением в доверенной среде. Этот адаптер не решает сетевой TOCTOU.
        return self.dispatch(tool,frozen)
