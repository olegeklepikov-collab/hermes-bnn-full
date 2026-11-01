#!/usr/bin/env python3
"""Проверить сборку полных контекстов всех процедур, не исполняя их содержание."""
from pathlib import Path
import argparse, datetime, json, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from gsd_bridge.service import Service
from gsd_bridge.common import MAX_CONTEXT_BYTES, canonical
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--report', type=Path, required=True)
a=p.parse_args();dest=a.report.expanduser().resolve()
if dest.exists() or dest.is_relative_to(ROOT):p.error('Нужен новый файл отчёта вне поставки')
s=Service();rows=[];started=time.monotonic()
for pid,definition in sorted(s.corpus.procedures.items()):
    t=time.monotonic()
    try:
        m=s.corpus.manifest(components=definition['owning_component'],procedure_ids=[pid])
        c=s.corpus.assemble_context(m,byte_limit=MAX_CONTEXT_BYTES)
        for entry in m['entries']:
            source=s.corpus.exact(entry['key'])
            if source['definition'] not in c['text'] or source['parent_context'] not in c['text']:
                raise AssertionError('Точный источник или родительский контекст не включён в текст: '+entry['key'])
        for contract in m['procedure_contracts']:
            if canonical(s.corpus.procedures[contract['id']]).decode() not in c['text']:
                raise AssertionError('Полный договор не включён в текст: '+contract['id'])
        row={'procedure':pid,'components':m['components'],'passed':True,'bytes':c['bytes'],
             'exact_sources_embedded':True,'full_procedure_contracts_embedded':True,
             'dependencies_included':len(m['procedure_contracts'])-1,'entries':len(m['entries']),
             'source_resolutions':m['source_resolutions'],'manifest_digest':m['digest'],'text_sha256':c['text_sha256']}
    except Exception as exc:
        row={'procedure':pid,'passed':False,'error':type(exc).__name__+': '+str(exc)}
    row['seconds']=round(time.monotonic()-t,3);rows.append(row)
    print(pid,row['passed'],row.get('bytes',row.get('error')),row['seconds'],flush=True)
data={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'total':len(rows),
      'passed':sum(x['passed'] for x in rows),'failed':sum(not x['passed'] for x in rows),
      'seconds':round(time.monotonic()-started,3),'scope':'Сборка полного контекста и зависимостей при активном владельце каждой процедуры. Не выполнение процедуры и не доставка модели.',
      'semantic_procedures_executed':0,'model_calls':0,'results':rows}
dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(bool(data['failed']))
