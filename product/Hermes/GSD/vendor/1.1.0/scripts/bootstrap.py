#!/usr/bin/env python3
"""Создать отдельное окружение Python вне поставки. Существующее не изменяет."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--venv',type=Path,required=True)
p.add_argument('--wheelhouse',type=Path)
a=p.parse_args();target=a.venv.expanduser().resolve()
if target.exists() or target.is_relative_to(ROOT):
    p.error('Укажите новый каталог окружения вне поставки')
if sys.version_info < (3,11):
    p.error('Требуется Python 3.11 или новее; совместимость конкретной версии подтверждается проверками')
venv.EnvBuilder(with_pip=True).create(target)
py=target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
args=[str(py),'-m','pip','install','-r',str(ROOT/'requirements.txt')]
if a.wheelhouse:
    args+=['--no-index','--find-links',str(a.wheelhouse.expanduser().resolve())]
subprocess.run(args,check=True)
subprocess.run([str(py),'-I','-B',str(ROOT/'gsd.py'),'verify','--engine-only'],check=True)
print(str(py))
