from pathlib import Path
import json,re
P=Path(__file__).resolve().parent;B=P.parent/'work/gsd-bundle';out=P/'skills';out.mkdir(exist_ok=True)
catalog=json.loads((B/'contracts/catalog.json').read_text())['entries'];mapping=[];seen=set()
for row in catalog:
 if row['kind']=='element':continue
 name='gsd-'+row['kind']+'-'+re.sub('[^a-zA-Z0-9_-]','-',row['id']).lower()
 if name in seen:raise ValueError('Duplicate skill alias')
 seen.add(name);data=json.loads((B/'engine'/row['path']).read_text())[row['collection']][row['index']]
 p=out/name/'SKILL.md';p.parent.mkdir(exist_ok=True)
 description='Адресная операция '+row['id']+'.'
 if len(description)>60:description='Исполнение точного договора GSD.'
 content=f'''---
name: {name}
description: {description}
version: 0.1.0
---

# {row['title']}

Источник: GSD Engine 3.0.3, интеграционный слой 1.1.0. Канонический адрес: `{row['key']}`. Смысловой владелец: **{row['owner']}**. Навык подключён к настоящему исполнителю через `gsd_work`; определение само не является исполнением.

## Когда применять

При готовых входах этой конкретной операции. Исходный договор приведён полностью ниже.

## Условия

Модуль `bn-gsd`, обязательный контроль и содержательный исполнитель должны быть доступны. Процедура требует готового случая `ProcedureEngine` и принятых зависимостей. Отсутствие данных, поставщика или приёмки сохраняется как незавершённость.

## Выполнение

1. Получите актуальный договор через `gsd_contract` с `key="{row['key']}"`.
2. Адресуйте реальные входы, контекст и версии; не создавайте наблюдений и прав из текста запроса.
3. Вызовите `gsd_work` с тем же ключом, входами и устойчивым `request_id`. Для процедуры передайте `run_id` готового случая.
4. Проверьте фактический продукт, происхождение и постусловие. Загрузка контекста и успешное завершение дочерней сессии не доказывают предметную истинность.
5. Сохраните ограничения и четыре остатка. Не повышайте статус и не выполняйте внешнее действие из факта наличия результата.

## Точный договор

```json
{json.dumps(data,ensure_ascii=False,indent=2)}
```

## Проверка

Фактические входы и версии совпадают; обязательный контекст доставлен полностью; исполнитель существует; выход адресуем; постусловие имеет конкретное свидетельство; ресурс учтён; неизвестность и непроверенное не названы успехом. Повтор после такого же отказа требует нового основания или исправления.
'''
 p.write_text(content);mapping.append({'source_key':row['key'],'role':row['owner'],'skill':'bn-gsd:'+name,'path':str(p.relative_to(P))})
root=out/'gsd-catalog';root.mkdir(exist_ok=True)
(root/'SKILL.md').write_text('''---
name: gsd-catalog
description: Адресный выбор операций и определений GSD.
version: 0.1.0
---

# Полный каталог GSD

`gsd_catalog` адресует все 1948 определений: 152 процедуры, 37 протоколов, 31 самостоятельный результат и 1728 исходных элементов. `gsd_contract` возвращает полный договор выбранного адреса. Первые 220 имеют отдельные навыки и маршрут настоящего исполнителя через `gsd_work`; исходные элементы служат определениями и не объявляются самостоятельными функциями.

G/S/D выполняются настоящими ограниченными дочерними сессиями. `gsd_analyze` соединяет их с оригинальными конечными алгоритмами. Состав, профиль, неизвестность, источник, версия и разрешение различаются. Отсутствующий компонент сохраняет своё обязательство.

Выберите точный адрес, проверьте готовность и зависимости, загрузите его полный навык. Нельзя выдавать загрузку либо вызов модели за предметную проверку. `gsd_runtime_status` показывает общий ресурс, `gsd_stop` останавливает семью.
''')
(P/'skill-map.json').write_text(json.dumps({'engine':'3.0.3','source_definitions':len(catalog),'operation_skills':mapping,'reference_elements':sum(r['kind']=='element'for r in catalog),'automatic_prompt_listing':False},ensure_ascii=False,indent=2))
print({'operation_skills':len(mapping),'source_definitions':len(catalog),'index_skill':1})
