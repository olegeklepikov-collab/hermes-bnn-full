"""Проверка и материализация канонических договоров v3 без повторной миграции схемы."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator
from _base import ROOT,load_json,digest

def check():
    schema=load_json(ROOT/'data/case.schema.json');Draft202012Validator.check_schema(schema)
    catalog=load_json(ROOT/'data/procedures.json');ids={p['id'] for p in catalog['procedures']}
    if len(ids)!=len(catalog['procedures']):raise ValueError('Повтор процедуры')
    for p in catalog['procedures']:
        if p['owning_component'] not in 'GSD' or not set(p['dependencies'])<=ids:raise ValueError('Неразрешённая зависимость')
        if not p['primary_operation'].strip() or not p['postcondition'].strip():raise ValueError('Пустой договор')
    return {'version':'3.0','procedures':len(ids),'schema_digest':digest(schema),'catalog_digest':digest(catalog)}
if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False,indent=2))
