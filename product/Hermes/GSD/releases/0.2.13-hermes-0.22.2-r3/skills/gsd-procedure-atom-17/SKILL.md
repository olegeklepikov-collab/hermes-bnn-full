---
name: gsd-procedure-atom-17
description: Адресная операция ATOM.17.
version: 0.1.0
---

# Связность P.T.J(V,A,R).S.M.C

Источник: GSD Engine 3.0.3, интеграционный слой 1.1.0. Канонический адрес: `procedure:ATOM.17`. Смысловой владелец: **S**. Навык подключён к настоящему исполнителю через `gsd_work`; определение само не является исполнением.

## Когда применять

При готовых входах этой конкретной операции. Исходный договор приведён полностью ниже.

## Условия

Модуль `bn-gsd`, обязательный контроль и содержательный исполнитель должны быть доступны. Процедура требует готового случая `ProcedureEngine` и принятых зависимостей. Отсутствие данных, поставщика или приёмки сохраняется как незавершённость.

## Выполнение

1. Получите актуальный договор через `gsd_contract` с `key="procedure:ATOM.17"`.
2. Адресуйте реальные входы, контекст и версии; не создавайте наблюдений и прав из текста запроса.
3. Вызовите `gsd_work` с тем же ключом, входами и устойчивым `request_id`. Для процедуры передайте `run_id` готового случая.
4. Проверьте фактический продукт, происхождение и постусловие. Загрузка контекста и успешное завершение дочерней сессии не доказывают предметную истинность.
5. Сохраните ограничения и четыре остатка. Не повышайте статус и не выполняйте внешнее действие из факта наличия результата.

## Точный договор

```json
{
  "id": "ATOM.17",
  "component": "ATOM",
  "title": "Связность P.T.J(V,A,R).S.M.C",
  "primary_operation": "Проверь предметное соответствие шести компонентов одному тезису.",
  "inputs": [
    "Полный Claim"
  ],
  "precondition": "Входы адресуемы и имеют версию; цель операции относится к контракту. Отсутствующий вход получает needs_data, не выдуманное значение.",
  "output_type": "Review целостности атома",
  "postcondition": "Не смешаны разные объекты, версии, проверки, модальности и области.",
  "pass_action": "Зафиксировать ProcedureRun с результатом, адресами выходов и проверкой постусловия; продолжить по очереди.",
  "failure_action": {
    "route": "ATOM.01",
    "rule": "Сохранить несоответствие и незавершённый статус; повтор возможен только после нового входа или исправления."
  },
  "mandatory_core": true,
  "minimum_profile_rank": 1,
  "execution_scope": "each_claim",
  "activation_trigger": null,
  "applicability_rule": "Ядро исполняется всегда; иная процедура включается по профилю или существенному триггеру. Неизвестный триггер требует оценки, не молчаливого пропуска.",
  "actor": "Агент; внешнее измерение, независимая проверка и разрешение — только реально доступный уполномоченный исполнитель.",
  "on_missing_input": "needs_data",
  "on_invalid_input": "needs_repair",
  "on_forbidden_use": "blocked",
  "source_anchors": [
    "strict:C-E001",
    "strict:C-D011",
    "strict:C-F004",
    "strict:C-F005"
  ],
  "negative_test_obligation": "Предъяви случай нарушения постусловия: «Не смешаны разные объекты, версии, проверки, модальности и области». Проверка должна зафиксировать несоответствие и не присваивать результат `pass`.",
  "version": "3.0",
  "owning_component": "S",
  "dependencies": [
    "ATOM.03",
    "ATOM.04",
    "ATOM.05",
    "ATOM.06",
    "ATOM.07",
    "ATOM.08",
    "ATOM.09",
    "ATOM.10",
    "ATOM.11",
    "ATOM.12",
    "ATOM.13",
    "ATOM.14",
    "ATOM.15",
    "ATOM.16"
  ],
  "read_set": [
    "contexts",
    "sources",
    "evidence",
    "claims"
  ],
  "write_set": [
    "claims"
  ],
  "input_selectors": [
    {
      "collection": "contexts",
      "minimum": 1
    },
    {
      "collection": "sources",
      "minimum": 0
    },
    {
      "collection": "evidence",
      "minimum": 0
    },
    {
      "collection": "claims",
      "minimum": 1
    }
  ],
  "dependency_policy": "required_when_active; otherwise explicit scoped_out reason",
  "allowed_effects": [
    "local_analysis"
  ],
  "preconditions": {
    "common": "Текущая версия, доступные адресные входы, неотозванные права и достаточный бюджет.",
    "specific": [
      "Полный Claim"
    ],
    "must_have_accepted_dependencies": [
      "ATOM.03",
      "ATOM.04",
      "ATOM.05",
      "ATOM.06",
      "ATOM.07",
      "ATOM.08",
      "ATOM.09",
      "ATOM.10",
      "ATOM.11",
      "ATOM.12",
      "ATOM.13",
      "ATOM.14",
      "ATOM.15",
      "ATOM.16"
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
    "strict:C-E001",
    "strict:C-D011",
    "strict:C-F004",
    "strict:C-F005"
  ]
}
```

## Проверка

Фактические входы и версии совпадают; обязательный контекст доставлен полностью; исполнитель существует; выход адресуем; постусловие имеет конкретное свидетельство; ресурс учтён; неизвестность и непроверенное не названы успехом. Повтор после такого же отказа требует нового основания или исправления.
