#!/usr/bin/env python3
"""Создать настройки в НОВОМ каталоге; не изменяет действующие настройки агента."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',choices=['hermes','vscode','cursor','claude','codex','generic'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--python',type=Path,default=Path(sys.executable))
    p.add_argument('--state-dir',type=Path,required=True)
    p.add_argument('--key-file',type=Path,required=True)
    a=p.parse_args()
    out=a.output.expanduser().resolve();py=a.python.expanduser().absolute()
    state=a.state_dir.expanduser().resolve();key=a.key_file.expanduser().resolve()
    if out.exists():
        p.error('Выходной каталог уже существует; перезапись запрещена')
    if out.is_relative_to(ROOT) or state.is_relative_to(ROOT) or key.is_relative_to(ROOT):
        p.error('Настройки и рабочие данные должны находиться вне поставки')
    if not py.is_file() or not key.is_file() or not state.is_dir():
        p.error('Нужны существующие Python, каталог состояния и отдельный ключ')
    if key.is_relative_to(state):
        p.error('Ключ не должен находиться в каталоге состояния')
    out.mkdir(mode=0o700,parents=True)
    env={'GSD_STATE_DIR':str(state),'GSD_TRUST_KEY_FILE':str(key),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
    server={'command':str(py),'args':['-I','-B',str(ROOT/'gsd.py'),'mcp'],'env':env}
    dump=lambda path,value:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.target=='hermes':
        directory=out/'plugins/gsd-integration';shutil.copytree(ROOT/'adapters/hermes',directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        dump(directory/'connection.json',{'bundle_root':str(ROOT),'python':str(py),'state_dir':str(state),
             'key_file':str(key),'enforce_analysis_only':True,'safe_read_tools':[]})
        # JSON является допустимым подмножеством YAML; файл не заменяет существующий config.yaml.
        dump(out/'native.config.fragment.json',{'plugins':{'enabled':['gsd-integration']}})
        dump(out/'mcp.config.fragment.json',{'mcp_servers':{'gsd':{**server,'timeout':180,'supports_parallel_tool_calls':False}}})
    elif a.target=='vscode':
        dump(out/'mcp.json',{'servers':{'gsd':{'type':'stdio',**server}}})
    elif a.target in ('cursor','claude','generic'):
        dump(out/('mcp.json' if a.target!='claude' else '.mcp.json'),{'mcpServers':{'gsd':server}})
    else:
        quoted=lambda x:json.dumps(x,ensure_ascii=False)
        text='[mcp_servers.gsd]\ncommand = '+quoted(str(py))+'\nargs = '+quoted(server['args'])+'\ntool_timeout_sec = 180\n\n[mcp_servers.gsd.env]\n'
        text+=''.join(k+' = '+quoted(v)+'\n' for k,v in env.items())
        (out/'config.fragment.toml').write_text(text,encoding='utf-8')
    shutil.copy2(ROOT/'adapters/ide/AGENTS.md',out/'AGENTS.gsd.md')
    dump(out/'configuration_receipt.json',{'target':a.target,'bundle':str(ROOT),'state':str(state),
        'active_host_modified':False,'host_acceptance':'not_performed','select_one_transport':True})
    print(str(out))

if __name__=='__main__':
    main()
