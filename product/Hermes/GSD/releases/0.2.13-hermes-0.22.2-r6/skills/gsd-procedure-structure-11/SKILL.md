---
name: gsd-procedure-structure-11
description: Адресная операция STRUCTURE.11.
version: 0.1.0
---

# Проверка факторной определённости

Источник: GSD Engine 3.0.3, интеграционный слой 1.1.0. Канонический адрес: `procedure:STRUCTURE.11`. Смысловой владелец: **S**. Навык подключён к настоящему исполнителю через `gsd_work`; определение само не является исполнением.

## Когда применять

При готовых входах этой конкретной операции. Исходный договор приведён полностью ниже.

## Условия

Модуль `bn-gsd`, обязательный контроль и содержательный исполнитель должны быть доступны. Процедура требует готового случая `ProcedureEngine` и принятых зависимостей. Отсутствие данных, поставщика или приёмки сохраняется как незавершённость.

## Выполнение

1. Получите актуальный договор через `gsd_contract` с `key="procedure:STRUCTURE.11"`.
2. Адресуйте реальные входы, контекст и версии; не создавайте наблюдений и прав из текста запроса.
3. Вызовите `gsd_work` с тем же ключом, входами и устойчивым `request_id`. Для процедуры передайте `run_id` готового случая.
4. Проверьте фактический продукт, происхождение и постусловие. Загрузка контекста и успешное завершение дочерней сессии не доказывают предметную истинность.
5. Сохраните ограничения и четыре остатка. Не повышайте статус и не выполняйте внешнее действие из факта наличия результата.

## Точный договор

```json
{
  "id": "STRUCTURE.11",
  "component": "STRUCTURE",
  "title": "Проверка факторной определённости",
  "primary_operation": "Установи, различимы ли выбранные скрытые параметры и альтернативные модели.",
  "inputs": [
    "Факторная модель и данные"
  ],
  "precondition": "Входы адресуемы и имеют версию; цель операции относится к контракту. Отсутствующий вход получает needs_data, не выдуманное значение.",
  "output_type": "IdentifiabilityReview",
  "postcondition": "Неидентифицируемый фактор не объявлен установленной сущностью.",
  "pass_action": "Зафиксировать ProcedureRun с результатом, адресами выходов и проверкой постусловия; продолжить по очереди.",
  "failure_action": {
    "route": "COMPARE.05",
    "rule": "Сохранить несоответствие и незавершённый статус; повтор возможен только после нового входа или исправления."
  },
  "mandatory_core": false,
  "minimum_profile_rank": 3,
  "execution_scope": "case",
  "activation_trigger": "multilevel",
  "applicability_rule": "Ядро исполняется всегда; иная процедура включается по профилю или существенному триггеру. Неизвестный триггер требует оценки, не молчаливого пропуска.",
  "actor": "Агент; внешнее измерение, независимая проверка и разрешение — только реально доступный уполномоченный исполнитель.",
  "on_missing_input": "needs_data",
  "on_invalid_input": "needs_repair",
  "on_forbidden_use": "blocked",
  "source_anchors": [
    "strict:C-A009",
    "strict:C-G003"
  ],
  "negative_test_obligation": "Предъяви случай нарушения постусловия: «Неидентифицируемый фактор не объявлен установленной сущностью». Проверка должна зафиксировать несоответствие и не присваивать результат `pass`.",
  "version": "3.0",
  "owning_component": "S",
  "dependencies": [
    "ATOM.17"
  ],
  "read_set": [
    "contexts",
    "claims",
    "relations",
    "models"
  ],
  "write_set": [
    "models"
  ],
  "input_selectors": [
    {
      "collection": "contexts",
      "minimum": 1
    },
    {
      "collection": "claims",
      "minimum": 0
    },
    {
      "collection": "relations",
      "minimum": 0
    },
    {
      "collection": "models",
      "minimum": 0
    }
  ],
  "dependency_policy": "required_when_active; otherwise explicit scoped_out reason",
  "allowed_effects": [
    "local_analysis"
  ],
  "preconditions": {
    "common": "Текущая версия, доступные адресные входы, неотозванные права и достаточный бюджет.",
    "specific": [
      "Факторная модель и данные"
    ],
    "must_have_accepted_dependencies": [
      "ATOM.17"
    ]
  },
  "consumer_limit_policy": "explicit_acceptance_required",
  "failure_routes": {
    "missing_input": "awaiting_evidence",
    "invalid_input": "needs_repair",
    "forbidden_use": "blocked",
    "budget": "partial",
    "stale_dependency": "reopened"
  },
  "release_status": "semantic_instruction_with_structural_controller",
  "legacy_source_anchors": [
    "strict:C-A009",
    "strict:C-G003"
  ]
}
```

## Проверка

Фактические входы и версии совпадают; обязательный контекст доставлен полностью; исполнитель существует; выход адресуем; постусловие имеет конкретное свидетельство; ресурс учтён; неизвестность и непроверенное не названы успехом. Повтор после такого же отказа требует нового основания или исправления.
