---
name: gsd-leaf-3c-s07-g05
description: Адресная операция 3C.S07.G05.
version: 0.1.0
---

# Проверить ровно указанное различение/основание; не выводить предметную истину из формы

Источник: GSD Engine 3.0.3, интеграционный слой 1.1.0. Канонический адрес: `leaf:3C.S07.G05`. Смысловой владелец: **S**. Навык подключён к настоящему исполнителю через `gsd_work`; определение само не является исполнением.

## Когда применять

При готовых входах этой конкретной операции. Исходный договор приведён полностью ниже.

## Условия

Модуль `bn-gsd`, обязательный контроль и содержательный исполнитель должны быть доступны. Процедура требует готового случая `ProcedureEngine` и принятых зависимостей. Отсутствие данных, поставщика или приёмки сохраняется как незавершённость.

## Выполнение

1. Получите актуальный договор через `gsd_contract` с `key="leaf:3C.S07.G05"`.
2. Адресуйте реальные входы, контекст и версии; не создавайте наблюдений и прав из текста запроса.
3. Вызовите `gsd_work` с тем же ключом, входами и устойчивым `request_id`. Для процедуры передайте `run_id` готового случая.
4. Проверьте фактический продукт, происхождение и постусловие. Загрузка контекста и успешное завершение дочерней сессии не доказывают предметную истинность.
5. Сохраните ограничения и четыре остатка. Не повышайте статус и не выполняйте внешнее действие из факта наличия результата.

## Точный договор

```json
{
  "id": "3C.S07.G05",
  "version": "3.0",
  "owning_component": "S",
  "source_key": "strict:G05:L3579",
  "source_digest": "3e43db80e143a1cd48a40c770afabf3598762634528299f9ebe0f185d9b4d040",
  "role": "strict_review",
  "operation_exact_source": "##### G05. decision_gate\r\n\r\nTrigger:\r\n\r\n```text\r\ntrigger_if: recommendation; decision; approve; stop; launch; assign; commit; deadline; owner\r\n```\r\n\r\nChecks:\r\n\r\n```text\r\nanalysis/recommendation/decision separation\r\nowner\r\naction\r\ndeadline\r\ncriterion\r\nfeedback loop\r\n```\r\n\r\nPass condition:\r\n\r\n```text\r\nrecommendation is not called decision without owner/action/deadline/criterion.\r\n```\r\n\r\nFail action:\r\n\r\n```text\r\nmark missing-decision status; ask for owner or state decision gap.\r\n```\r\n\r\n",
  "required_input": [
    "task_and_C",
    "versioned_target_or_seed",
    "applicability_reason",
    "available_material",
    "budget"
  ],
  "output_type": "BoundedReviewOrDerivation",
  "postcondition": "Проверить ровно указанное различение/основание; не выводить предметную истину из формы",
  "universal_constraint": "COMMON.md: не смешивать определение, исполнение, проверку и допуск",
  "semantic_executor": "AI-agent_or_domain_reviewer",
  "programmatic_guarantee": "Точная адресация, тип и сохранение переданных границ; не автоматическое доказательство смысла",
  "parent": "3C.S07",
  "per_target": true
}
```

## Проверка

Фактические входы и версии совпадают; обязательный контекст доставлен полностью; исполнитель существует; выход адресуем; постусловие имеет конкретное свидетельство; ресурс учтён; неизвестность и непроверенное не названы успехом. Повтор после такого же отказа требует нового основания или исправления.
