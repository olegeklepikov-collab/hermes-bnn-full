#!/usr/bin/env python3
"""Build a code/documentation/evidence package. Operator state and credentials are excluded."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import zipfile

PACKAGE = Path(__file__).resolve().parent
WORK = PACKAGE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--destination", required=True); parser.add_argument("--redact-map")
    args = parser.parse_args(); destination = Path(args.destination).resolve()
    redactions=json.loads(Path(args.redact_map).read_text()) if args.redact_map else []
    if destination.exists(): raise ValueError("Delivery already exists; choose a new immutable destination")
    evidence = PACKAGE / "evidence"; evidence.mkdir(exist_ok=True)
    selected = [
        "integration-upstream-tests.json", "integration-integrity.json", "patch-roundtrip.json",
        "profile-rollback-check.json", "bootstrap-required-binding.json", "auxiliary-live-positive.json",
        "semantic-products-1.json", "semantic-products-2.json", "semantic-products-3.json",
        "semantic-arguments-1.json", "semantic-arguments-2.json", "semantic-arguments-3.json",
        "gateway-required-control-negative.json", "gateway-cancellation-v2.json",
        "procedure-live-products.json", "procedure-live-arguments.json", "procedure-operator-admission.json",
        "procedure-stop-resume.json", "procedure-closure-native.json", "work-file-arguments.json",
        "final-contract-suite.log", "final-host-suite.log", "portable-host-tests.log",
        "managed-update-tests.log", "empty-child-toolsets.log", "delegation-regression.log",
        "auxiliary-terminal-regression.log", "auxiliary-provider-regression-2.log",
        "baseline-overlay-tests.log", "update-stage-current.log",
        "native-skill-learning-check.json", "production-acceptance.json", "main-telegram-success.json", "main-gateway-live.json",
        "main-negative-controls.json", "main-unapproved-publication.json", "main-seven-routes-six-profiles.json",
        "main-r-plot.json", "main-native-web-search.json", "os-sandbox-real.json", "joint-tools-lab.json",
        "external-native-products.json", "external-native-owner-admission.json", "signed-state-transfer.json",
        "rollback-files-0.2.1.json", "final-stage-controls-0.2.2.log", "final-host-controls-0.2.2.log",
        "final-restored-cli-0.2.2.log", "final-native-leaf-0.2.2.log",
        "linked-new-run-live.json", "work-file-products.json", "natural-intent-query.txt",
        "natural-intent-products-v1.json", "natural-intent-products-v2.json", "natural-intent-products-v3.json",
    ]
    # Full inputs and native products are preserved. No auth stores, keys,
    # active-session databases, raw SDK responses or old capability-bearing logs.
    for name in selected:
        source = WORK / "results" / name
        if not source.exists(): raise ValueError("Missing actual evidence: " + name)
        shutil.copy2(source, evidence / name)
    shutil.copy2(WORK / "design/semantic-trials.json", evidence / "semantic-criteria-before-trials.json")
    for name in ["natural-intent-criteria.json", "natural-intent-criteria-v2.json", "natural-intent-criteria-v3.json"]:
        shutil.copy2(WORK / "design" / name, evidence / name)
    shutil.copy2(WORK / "results/upstream-run-1/summary.json", evidence / "source-engine-checks.json")
    shutil.copy2(WORK / "design/acceptance-plan.json", evidence / "acceptance-plan-before-trials.json")
    plan = json.loads((WORK / "design/acceptance-plan.json").read_text())
    original = json.loads((WORK / "results/integration-upstream-tests.json").read_text())
    passed_names = {r["id"].split(".")[-1] for r in original["tests"] if r["passed"]}
    controls = ["final-contract-suite.log", "portable-host-tests.log"]
    live = ["semantic-products-1.json", "semantic-products-2.json", "semantic-products-3.json"]
    mapping = {
        "PKG-01": ("verified", "Неизменённые источники, дерево и манифесты", ["integration-integrity.json"]),
        "PKG-02": ("verified", "285 файлов; 283 записи внешнего и 139 записей внутреннего манифеста", ["integration-integrity.json"]),
        "CTX-03": ("verified_with_scope", "Точные полные аргументы запросов реальных G/S/D; смысловое соблюдение отдельно", live),
        "EXE-06": ("partial", "Три общих смысловых прогона, две адресные операции, BOOT.01/02; не все 152 процедуры по отдельности", live + ["procedure-closure-native.json"]),
        "STATE-07": ("verified_with_scope", "Чужая семья не читает случай/продукт; операторская привязка сохраняет идентичность; A/B/A проверено для обязательного контроля", controls),
        "RESOURCE-02": ("verified_with_scope", "Общий сохраняемый ресурс семьи; основной, дочерний и вспомогательный расход; финансовый бюджет внешних служб не обещан", controls + ["auxiliary-live-positive.json", "gateway-cancellation-v2.json"]),
        "HANDOFF-01": ("verified_with_scope", "Исходные ProductRegistry/HandoffChannel, версии, отпечатки, остатки; фактические потребители S/D", live),
        "HANDOFF-02": ("verified_with_scope", "Доставка и резерв сохраняются транзакционно; результат модели остаётся unreviewed", live),
        "PROVIDER-02": ("verified", "Настоящий openai-codex / gpt-6.1-sol; фактический расход и неизвестный резерв", live + ["auxiliary-live-positive.json"]),
        "GSD-I03": ("partial", "Исходные семь маршрутов и ожидание внешнего владельца сохранены; приём внешних процедурных квитанций через worker не настроен", ["integration-upstream-tests.json"]),
        "GSD-I06": ("partial", "Привязка, продолжение и связанный новый запуск без пополнения проверены; универсальная миграция через хост не подключена", ["procedure-stop-resume.json", "linked-new-run-live.json", "portable-host-tests.log"]),
        "HERMES-02": ("verified_with_scope", "Настоящие CLI, локальный шлюз и дети испытательной копии", live),
        "IDE-02": ("not_tested", "Отдельные среды разработки не подключались и не заявлены действующими", []),
        "ACTION-02": ("partial", "Обязательные точки в инструментах, соединителях, запросах и детях; прежние произвольные исполнители запрещены, не адаптированы", controls + ["gateway-required-control-negative.json"]),
        "CHANNEL-01": ("not_connected", "Для GSD проверен локальный HTTP-шлюз, не Telegram от конца до конца", []),
        "OPS-01": ("partial", "Остановка, продолжение, точная текущая копия и откат проверены; универсальная миграция старых снимков не реализована", ["profile-rollback-check.json", "procedure-stop-resume.json", "patch-roundtrip.json"]),
        "BN-GUARD-01": ("verified_with_scope", "Отсутствие, исключение, зависание, неверный ответ и разрыв связи закрывают защищённый путь", controls + ["gateway-required-control-negative.json", "bootstrap-required-binding.json"]),
        "BN-ROLES-01": ("verified", "Настоящие ограниченные дочерние роли; точные продукты и запрет расширения полномочий", live + ["gateway-cancellation-v2.json"]),
        "BN-CONTEXT-01": ("verified_with_scope", "Полное ядро, адресное замыкание и инженерный источник; независимые записи разбиваются, неделимое не усекается", controls + ["procedure-closure-native.json"]),
        "BN-BUDGET-01": ("verified_with_scope", "Общий ресурс сохраняемой семьи; самостоятельные новые задачи имеют свои семьи", controls + ["auxiliary-live-positive.json", "procedure-stop-resume.json"]),
        "BN-STATE-01": ("partial", "Версии, остановка, отзыв точного разрешения, отмена и операторское продолжение; произвольная старая миграция ограничена", controls + ["gateway-cancellation-v2.json", "procedure-stop-resume.json"]),
        "BN-CATALOG-01": ("verified_with_scope", "1 948 адресов; 220 полных навыков операций, указатель и оркестрация; отдельные настоящие исполненные операции", ["integration-upstream-tests.json", "procedure-live-products.json", "procedure-closure-native.json"]),
        "BN-MODES-01": ("verified_with_scope", "Все семь исходных составов и границы зависимостей программно проверены; не все живые смысловые составы отдельно", ["integration-upstream-tests.json"] + live),
        "BN-PROFILES-01": ("verified_with_scope", "Все шесть исходных профилей и запрет понижения сохранены; независимая экспертиза не подставлена", ["source-engine-checks.json", "integration-upstream-tests.json"]),
        "BN-RELEASE-01": ("verified", "N09–N11 и исправления 1.1.0 сохранены; повторное использование/отвод подтверждены живыми прогонами", ["source-engine-checks.json", "integration-upstream-tests.json"] + live),
        "BN-UPGRADE-01": ("partial", "Тот же commit: отдельный кандидат, замороженные зависимости, проверка/отказ/откат; будущие версии и рабочие службы ещё не приняты", ["update-stage-current.log", "patch-roundtrip.json", "profile-rollback-check.json", "baseline-overlay-tests.log"]),
        "BN-SURFACES-01": ("verified_with_scope", "CLI, настоящий локальный gateway, дети и отрицательные пути; основной экземпляр не переключён", live + ["gateway-required-control-negative.json", "gateway-cancellation-v2.json"]),
        "BN-SEMANTIC-01": ("partial", "Три общих синтетических прогона и обычное намерение после выявленных исправлений; SEM-04/06 проверены механизмами; отдельная IDE и универсальная предметная приёмка отсутствуют", live + controls + ["natural-intent-products-v3.json"]),
    }
    # Keep the original requirement IDs; revise actual results from evidence, not intent.
    production=["production-acceptance.json","main-telegram-success.json","main-gateway-live.json"]
    mapping.update({
        "EXE-06":("verified_with_scope","Настоящие содержательные G/S/D, адресные операции и внешний BOOT.01; отдельная предметная проверка всех 152 не заявлена",live+production+["external-native-products.json"]),
        "GSD-I03":("verified_with_scope","42 сочетания маршрутов/профилей; настоящий внешний D, исходная подписанная квитанция и сохранение локального G",["main-seven-routes-six-profiles.json","external-native-owner-admission.json"]),
        "GSD-I06":("verified_with_scope","Текущий подписанный снимок перенесён без изменения ресурса/заданий; новый связанный запуск не сбрасывает расход; неизвестная старая история закрыта",["signed-state-transfer.json","linked-new-run-live.json","final-host-controls-0.2.2.log"]),
        "HERMES-02":("verified_with_scope","Основной экземпляр: CLI, HTTP, приложение, настоящий Telegram и дочерние роли",production),
        "ACTION-02":("verified_with_scope","Обязательные границы всех модельных путей; изоляция ОС; явные прежние инструменты; при исчезновении политики новый процесс закрыт",["main-negative-controls.json","main-unapproved-publication.json","os-sandbox-real.json","final-stage-controls-0.2.2.log"]),
        "CHANNEL-01":("verified","Настоящий входящий запрос владельца, три завершённых роли и ответ Telegram после исправления восстановления",["main-telegram-success.json"]),
        "OPS-01":("verified_with_scope","Резервы, отзыв, продолжение, перенос согласованного снимка и файловый откат проверены; старый неизвестный расход не угадывается",["signed-state-transfer.json","rollback-files-0.2.1.json","final-host-controls-0.2.2.log"]),
        "BN-STATE-01":("verified_with_scope","Основной восстановленный сеанс, отзыв, остановка, отмена, консервативное восстановление погибшего запроса и сохранение расхода",["main-telegram-success.json","final-restored-cli-0.2.2.log","final-host-controls-0.2.2.log","signed-state-transfer.json"]),
        "BN-UPGRADE-01":("verified_with_scope","Отдельный кандидат того же commit, замороженные зависимости, 54 проверки, сохранение прежней заплатки; будущий commit допускается только после его испытаний",["final-stage-controls-0.2.2.log","rollback-files-0.2.1.json","patch-roundtrip.json"]),
        "BN-SURFACES-01":("verified_with_scope","Основные CLI, HTTP, приложение, настоящий Telegram и ограниченные дочерние роли; окончательный выпуск дополнительно исполнил S",production+["final-native-leaf-0.2.2.log"]),
        "BN-MODES-01":("verified_with_scope","Все семь составов и шесть профилей проверены в 42 настоящих исходных случаях; отсутствующие обязательства не удаляются",["main-seven-routes-six-profiles.json","external-native-owner-admission.json"]+live),
        "BN-PROFILES-01":("verified_with_scope","Шесть профилей сохранены; нужная независимая экспертиза не подменяется ролью модели",["source-engine-checks.json","main-seven-routes-six-profiles.json"]),
        "BN-SEMANTIC-01":("verified_with_scope","Три заданных предметных прогона, обычное намерение и основные CLI/HTTP/Telegram сохраняют причинную неопределённость; всеобщая предметная приёмка не заявлена",live+production+["natural-intent-products-v3.json"]),
    })
    source = "source/GSD_Integration/"
    implementation_groups = {
        "PKG": source + "manifest.json, gsd_bridge/common.py:verify_tree; worker.py:execute",
        "DEF": source + "gsd_bridge/service.py:catalog/contract; build_skills.py; skill-map.json",
        "CTX": source + "gsd_bridge/context.py:ContextAssembler; worker.py:job_create/procedure_inputs/prepare_work_file; bn_gsd/runtime.py:request_middleware/model_control",
        "EXE": source + "gsd_bridge/composition.py; engine/tools/triad.py; bn_gsd/runtime.py:analyze/work; bn_gsd/roles.py:NativeRoles.run",
        "STATE": source + "gsd_bridge/store.py/lifecycle.py; worker.py:model_engine/operator_commit; bn_gsd/ledger.py:bind_case/own_case/own_product",
        "RESOURCE": source + "engine/tools/triad.py:SharedBudget; bn_gsd/ledger.py:reserve/settle/tool_call; bn_gsd/runtime.py:model_control/post_api",
        "HANDOFF": source + "gsd_bridge/products.py; engine/tools/triad.py:HandoffChannel; worker.py:native_handoff; bn_gsd/ledger.py:reserve",
        "PROVIDER": source + "gsd_bridge/provider.py; provider_receipt.py; bn_gsd/roles.py:run; Hermes agent/auxiliary_hooks.py",
        "MCP": source + "gsd_bridge/mcp.py",
        "HERMES": "plugin/__init__.py:register; bn_gsd/runtime.py; Hermes hermes_cli/plugins.py/middleware.py/execution_control.py",
        "IDE": source + "scripts/configure.py; adapters/ide/",
        "ACTION": source + "adapters/host_guard.py; bn_gsd/effects.py; Hermes tools/registry.py, tools/connectors/dispatch.py, hermes_cli/middleware.py",
        "CHANNEL": "Основной native API gateway и Telegram; bn_gsd/runtime.py:bound_state; production-acceptance.json",
        "OPS": "operator.py; configure_profile.py; rollback_profile.py; runtime_guard.py; stage_update.py; worker.py:check_anchor",
        "GSD": source + "gsd_bridge/composition.py/context.py/routes.py/products.py/lifecycle.py; worker.py",
        "BN": "plugin/__init__.py; bn_gsd/runtime.py/roles.py/ledger.py; worker.py; runtime_guard.py; native core patch",
    }
    executed_native = {
        "BN-GUARD-01": ["test_missing_required_controller_prevents_real_effect", "test_failed_required_controller_never_falls_through", "test_direct_connector_dispatch_cannot_bypass_required_control", "gateway missing-controller live response"],
        "BN-ROLES-01": ["test_explicit_empty_toolsets_do_not_inherit_parent_or_mcp", "three real native G/S/D trials", "real gateway native-child interruption"],
        "BN-CONTEXT-01": ["test_partition_covers_complete_source_and_never_splits_mandatory_context", "two real engineering leaf operations", "real BOOT.02 addressed data closure"],
        "BN-BUDGET-01": ["test_shared_concurrent_reservations_unknown_cost_and_completion_reserve", "actual AUXOK usage delta", "actual source+host stop/resume without refill"],
        "BN-STATE-01": ["test_rollback_mismatch_missing_key_and_exact_copy_recovery", "test_dead_owner_is_not_respawned_and_unsettled_usage_is_preserved", "real gateway interruption and durable duplicate creation"],
        "BN-CATALOG-01": ["source exact catalog contracts", "native 3C.S06.A", "native BOOT.01/02 and separate operator admission"],
        "BN-MODES-01": ["test_all_seven_modes_actual_outputs", "test_missing_provider_explicit", "three actual native GSD trials"],
        "BN-PROFILES-01": ["source engine six-profile system tests", "test_case_agent_cannot_raise_budget"],
        "BN-RELEASE-01": ["source 331 remediation cases and 470 residual cases", "three native generation known/withdrawn candidate trials"],
        "BN-UPGRADE-01": ["actual fresh frozen current-commit candidate", "actual patch install/reverse/hash roundtrip", "actual installation+configuration rollback", "test_external_manager_refuses_direct_apply_before_backup"],
        "BN-SURFACES-01": ["actual CLI/provider requests", "actual API gateway responses", "actual native child products", "actual gateway missing-controller denial and stop"],
        "BN-SEMANTIC-01": ["semantic-review.json", "SEM-04 source freshness tests", "SEM-06 actual guarded file tests"],
    }
    for r in plan["requirements"]:
        if r["id"] in mapping:
            result, fact, paths = mapping[r["id"]]
        elif r["checks"] and all(c in passed_names for c in r["checks"]):
            result, fact, paths = "verified_source_contract", "Именованные исходные испытания прошли; их уровень не повышен до смысловой/внешней приёмки", ["integration-upstream-tests.json"]
        elif r["id"].startswith("GSD-I"):
            result, fact, paths = "verified_source_contract", "Договоры исправлений 1.1.0 проверены исходными испытаниями; отсутствующий адаптер/внешний владелец не подставлены", ["integration-upstream-tests.json", "integration-integrity.json"]
        else:
            result, fact, paths = "not_tested", "Отдельное фактическое подтверждение отсутствует", []
        executed = executed_native.get(r["id"], [x for x in r["checks"] if x in passed_names])
        r.update(actual_result=result, actual_fact=fact,
                 implementation=implementation_groups[r["id"].split("-")[0]], executed_checks=executed,
                 evidence=[{"file": name, "sha256": sha(evidence / name)} for name in paths])
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    plan["overall"] = "operational_main_Hermes_target_verified_with_scoped_semantic_acceptance"
    plan["full_supplier_all_host_acceptance"] = False
    plan["universal_semantic_acceptance"] = False
    (evidence / "acceptance-results.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    rows = ["# Матрица требований", "", "Исходные ID и критерии сохранены. Подробные проверки и отпечатки свидетельств — в `evidence/acceptance-results.json`. Общий результат: рабочий Hermes BN подключён и испытан. Полная приёмка всех иных хостов поставщика и всеобщая предметная корректность не заявлены; отдельная IDE остаётся непроверенной.", "", "| ID / источник | Требование | Механизм / реализация | Проверка | Фактический результат |", "|---|---|---|---|---|"]
    for r in plan["requirements"]:
        cell = lambda s: str(s).replace("|", " / ").replace("\n", " ")
        checks = ", ".join(r["executed_checks"]) or ", ".join(x["file"] for x in r["evidence"]) or "не выполнена"
        rows.append("| " + " | ".join(map(cell, [r["id"] + " · " + ", ".join(r["source_ids"]), r["requirement"], r["mechanism"] + "; " + r["implementation"], checks, r["actual_result"] + ": " + r["actual_fact"]])) + " |")
    (PACKAGE / "docs/05-Матрица.md").write_text("\n".join(rows) + "\n")
    # Semantic judgments are explicit scoped human/operator review, not keyword scores.
    judgments = {"criteria_sha256": sha(WORK / "design/semantic-trials.json"),
        "criteria_mtime_utc": datetime.fromtimestamp((WORK / "design/semantic-trials.json").stat().st_mtime, timezone.utc).isoformat(),
        "review_type": "operator_read_actual_products_against_fixed_synthetic_criteria", "universal_acceptance": False, "trials": []}
    for n in range(1, 4):
        data = json.loads((evidence / f"semantic-products-{n}.json").read_text())
        first = min(j["created_at"] for j in data["jobs"].values())
        assert (WORK / "design/semantic-trials.json").stat().st_mtime < first
        assert all(j["status"] == "completed" and j["native_receipt"]["terminal_state"] == "SUCCEEDED" for j in data["jobs"].values())
        judgments["trials"].append({"trial": n, "session_id": data["session_id"], "roles": sorted(data["jobs"]),
            "criterion_before_first_role": True, "known_candidate_preserved": True, "withdrawal_preserved": True,
            "process_vs_measurement_preserved": True, "dependent_sources_not_counted_as_independent": True,
            "invalid_and_unknown_not_refutation": True, "synthetic_code_max_mean_distinguished": True,
            "causal_truth_not_claimed": True, "next_measurement_planned_not_fabricated": True,
            "evidence": f"semantic-products-{n}.json"})
    (evidence / "semantic-review.json").write_text(json.dumps(judgments, ensure_ascii=False, indent=2))
    natural = {"query_mentions_tools": False, "query_sha256": sha(WORK / "results/natural-intent-query.txt"),
        "v1": "failed composite: genuine G completed, S/D closed by literal SCOPE_MISMATCH; not acceptance",
        "v2": "native G/S/D completed; semantic gap: predictions not addressed clearly inside nested packet",
        "v3": "native G/S/D completed; direct candidate/review/predecessor views understood; finite matched-key comparison distinguished from subject-matter uncertainty",
        "acceptance_scope": "one ordinary synthetic business question, no external data collection, no universal routing guarantee",
        "operator_review": "actual S/D products and final response read; causal uncertainty, dependent retellings and planned-not-executed check preserved"}
    (evidence / "natural-intent-review.json").write_text(json.dumps(natural, ensure_ascii=False, indent=2))
    audit = {"engine": "3.0.3", "integration": "1.1.0", "protocol": "3.0", "comparison_contract": "3.0.2",
        "source_archive_sha256": plan["source_archive_sha256"], "source_archive_files": 285,
        "outer_manifest_entries": 283, "engine_manifest_entries": 139,
        "hermes_commit": plan["hermes_commit"], "hermes_release": "2026.9.24", "hermes_package": "0.21.5", "python": "3.13.14",
        "original_lab_adapter_1_2": "not_supplied", "gsd_git_commit": "not_supplied", "gsd_license_file": "not_found",
        "historical_material_active": False, "active_core_config_services_changed": True,
        "credentials_in_delivery": False, "test_authorization": "owner canonical auth store; no copied rotating tokens"}
    (evidence / "audit-summary.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    def anonymise(value):
        if isinstance(value,dict):return {k:anonymise(v) for k,v in value.items()}
        if isinstance(value,list):return [anonymise(v) for v in value]
        if isinstance(value,str):
            for old,new in redactions:value=value.replace(str(old),str(new))
        if isinstance(value,int) and not isinstance(value,bool):
            for old,new in redactions:
                if str(value)==str(old):return new
        return value
    for path in evidence.iterdir():
        if path.suffix==".json":
            path.write_text(json.dumps(anonymise(json.loads(path.read_text())),ensure_ascii=False,indent=2))
        elif path.is_file():path.write_text(anonymise(path.read_text(errors="replace")))
    # Re-seal evidence references after account redaction.
    acceptance=json.loads((evidence/"acceptance-results.json").read_text())
    for row in acceptance["requirements"]:
        for item in row["evidence"]:item["sha256"]=sha(evidence/item["file"])
    (evidence/"acceptance-results.json").write_text(json.dumps(acceptance,ensure_ascii=False,indent=2))
    shutil.copytree(PACKAGE, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store"))
    shutil.copytree(WORK / "work/gsd-bundle", destination / "source/GSD_Integration",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    baseline = destination / "source/hermes-base-f97608f.tar.gz"
    subprocess.run(["git", "archive", "--format=tar.gz", "--output=" + str(baseline), plan["hermes_commit"]],
                   cwd=WORK / "work/hermes-agent", check=True)
    files = {str(path.relative_to(destination)): sha(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    manifest = {"format": "hermes-bn-gsd-delivery/0.2.2", "created_at": datetime.now(timezone.utc).isoformat(),
                "overall": plan["overall"], "files": files, "excluded": ["operator keys", "auth stores", "runtime databases", "private sessions", "raw SDK responses"]}
    (destination / "delivery-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (destination / "SHA256SUMS").write_text("".join(value + "  " + name + "\n" for name, value in files.items()))
    archive = destination.parent / (destination.name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(destination.rglob("*")):
            if path.is_file(): z.write(path, str(Path(destination.name) / path.relative_to(destination)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError("Delivery CRC validation failed")
    archive.chmod(0o600)
    result = {"archive": str(archive), "sha256": sha(archive), "bytes": archive.stat().st_size, "files": len(files), "overall": plan["overall"]}
    (WORK / "results/delivery-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
