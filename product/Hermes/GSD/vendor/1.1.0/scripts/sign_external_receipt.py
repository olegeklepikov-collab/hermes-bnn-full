#!/usr/bin/env python3
"""Подписать квитанцию внешнего исполнителя. Только доверенный оператор.

Подпись удостоверяет источник, но не устанавливает истинность его сообщения.
Ключ и этот путь запуска не предоставляются модельному инструменту.
"""
from pathlib import Path
import argparse
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from gsd_bridge.common import canonical,load,BridgeError
from gsd_bridge.routes import signature
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();key=a.key_file.expanduser().resolve();out=a.output.expanduser().resolve()
try:
    if out.exists() or out.is_relative_to(ROOT):
        raise BridgeError('OUTPUT_PATH','Выберите новый файл вне поставки')
    if not key.is_file() or (os.name=='posix' and key.stat().st_mode & 0o077):
        raise BridgeError('KEY_PERMISSIONS','Ключ должен быть доступен только владельцу')
    raw=key.read_bytes()
    if len(raw)!=32:raise BridgeError('KEY_SIZE','Требуется ровно 32 байта')
    body=load(a.input)
    if not isinstance(body,dict) or 'signature' in body:
        raise BridgeError('RECEIPT','Нужен объект неподписанной квитанции')
    receipt={**body,'signature':signature(body,raw)}
    from jsonschema import Draft202012Validator
    Draft202012Validator(load(ROOT/'contracts/external_receipt.schema.json')).validate(receipt)
    out.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(out,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:f.write(canonical({'receipt':receipt})+b'\n')
    print(str(out))
except Exception as exc:
    print(str(exc),file=sys.stderr);raise SystemExit(2)
