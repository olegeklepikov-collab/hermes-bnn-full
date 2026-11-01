#!/usr/bin/env python3
"""Собрать полный контекст в новый каталог вне поставки; не означает чтение моделью."""
from pathlib import Path
import argparse, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from gsd_bridge.service import Service,MODES
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--components',choices=MODES,required=True)
p.add_argument('--profile',choices=['standard','engineering'],default='standard');p.add_argument('--procedure-id',action='append',default=[])
p.add_argument('--entry-key',action='append',default=[]);p.add_argument('--byte-limit',type=int,default=1500000)
p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.expanduser().resolve()
if out.exists() or out.is_relative_to(ROOT):p.error('Требуется новый каталог вне поставки')
value=Service().call('gsd_context',{'components':a.components,'entry_keys':a.entry_key,'byte_limit':a.byte_limit,'profile':a.profile,'procedure_ids':a.procedure_id})
if not value['ok']:
 print(json.dumps(value,ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
r=value['result'];text=r['text'].encode('utf-8');out.mkdir(parents=True,mode=0o700)
(out/'context.md').write_bytes(text)
(out/'manifest.json').write_text(json.dumps(r['manifest'],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
receipt={'components':a.components,'bytes':len(text),'sha256':hashlib.sha256(text).hexdigest(),'manifest_digest':r['manifest_digest'],
         'complete_assembly':True,'model_delivery_verified':False,'semantic_adherence_verified':False}
(out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(str(out))
