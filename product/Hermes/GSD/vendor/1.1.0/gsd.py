#!/usr/bin/env python3
"""Командный интерфейс GSD Integration. Запускается также через Python -I."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from gsd_bridge.common import canonical, read_json, load, verify_tree, BridgeError, MAX_JSON_BYTES

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    verify=commands.add_parser('verify');verify.add_argument('--engine-only',action='store_true')
    commands.add_parser('mcp')
    call=commands.add_parser('call');call.add_argument('tool');call.add_argument('--json',default='-')
    init=commands.add_parser('init-state');init.add_argument('--state-dir',required=True);init.add_argument('--key-file',required=True)
    resume=commands.add_parser('resume');resume.add_argument('--run-id',required=True);resume.add_argument('--revision',type=int,required=True);resume.add_argument('--reason',required=True);resume.add_argument('--host-control',action='store_true',required=True)
    host=commands.add_parser('host-command');host.add_argument('operation',choices=['new-run','external-commit','migrate-state']);host.add_argument('--json',required=True);host.add_argument('--host-control',action='store_true',required=True)
    args=parser.parse_args()
    try:
        if args.command=='verify':
            result=verify_tree(ROOT/'engine' if args.engine_only else ROOT)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['valid'] else 2
        if args.command=='init-state':
            state=Path(args.state_dir).expanduser().resolve();key=Path(args.key_file).expanduser().resolve()
            if state.is_relative_to(ROOT) or key.is_relative_to(ROOT) or key.is_relative_to(state):
                raise BridgeError('UNSAFE_PATH','Состояние и отдельный ключ должны находиться вне поставки')
            if state.exists() and any(state.iterdir()):
                raise BridgeError('STATE_EXISTS','Нельзя повторно инициализировать непустое состояние')
            if key.exists():
                raise BridgeError('KEY_EXISTS','Существующий ключ не заменяется')
            state.mkdir(mode=0o700,parents=True,exist_ok=True)
            key.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:
                f.write(secrets.token_bytes(32));f.flush();os.fsync(f.fileno())
            os.environ['GSD_STATE_DIR']=str(state);os.environ['GSD_TRUST_KEY_FILE']=str(key)
            from gsd_bridge.store import Store
            Store()
            print(json.dumps({'ok':True,'GSD_STATE_DIR':str(state),'GSD_TRUST_KEY_FILE':str(key)},ensure_ascii=False,indent=2));return 0
        if args.command=='mcp':
            from gsd_bridge.mcp import MCPServer
            MCPServer().serve();return 0
        from gsd_bridge.service import Service
        service=Service()
        if args.command=='status':
            result=service.call('gsd_status',{})
        elif args.command=='host-command':
            value=load(Path(args.json))
            if not isinstance(value,dict):
                raise BridgeError('INVALID_INPUT','Ожидается объект команды оператора')
            functions={'new-run':service.new_run_by_host,'external-commit':service.external_commit_by_host,'migrate-state':service.migrate_by_host}
            result={'ok':True,'result':functions[args.operation](**value)}
        elif args.command=='resume':
            result={'ok':True,'result':service.resume_by_host(args.run_id,args.revision,args.reason)}
        else:
            value=read_json(sys.stdin.buffer.read(MAX_JSON_BYTES+1)) if args.json=='-' else load(Path(args.json))
            result=service.call(args.tool,value)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        inner=result.get('result',{})
        return 0 if result.get('ok') and inner.get('effective_status')!='failed' and inner.get('operation_accepted') is not False else 2
    except Exception as exc:
        error={'ok':False,'error':{'code':getattr(exc,'code','LOCAL_ERROR'),'message':str(exc)}}
        # Ошибка запуска MCP не должна загрязнять его stdout.
        print(json.dumps(error,ensure_ascii=False),file=sys.stderr if args.command=='mcp' else sys.stdout)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
