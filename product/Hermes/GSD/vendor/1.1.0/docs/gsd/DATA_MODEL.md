# GSD — модель данных

## Содержание

- [1. Назначение и граница](#gsd-section-001)
- [2. Объекты и смысловые связи](#gsd-section-002)
- [3. Claim и независимые координаты](#gsd-section-003)
- [4. Состояния и области применения](#gsd-section-004)
- [5. Идентичность и целостность](#gsd-section-005)
- [6. Обязательные поля схемы случая](#gsd-section-006)
- [7. Реестры определений](#gsd-section-007)

---

<a id="gsd-section-001"></a>

## 1. Назначение и граница

Модель разделяет исходный материал, утверждение, проверку, модель, решение, право и фактическое исполнение. Синтаксически корректный объект не становится достоверным от прохождения схемы. Предметная обоснованность проверяется S; достаточность диагноза — в контексте D; полномочие — по отдельному договору действия.

`RawInput` содержит полученный материал; `Draft` — неполные рабочие записи; `ValidatedCase` — случай, удовлетворяющий структурным и межобъектным требованиям. Состояние данных не заменяет эпистемического статуса содержащихся в них утверждений.

Машинная структура случая определяется [case.schema.json](schemas/case.schema.json). Заголовок передачи и конечный проверочный пакет имеют собственные схемы. Типы `Candidate`, `GenerationRequest`, `CandidateSet`, `TestPlan` и `DiagnosticResult` дополнительно описываются в протоколах компонентов и [договорах интерфейсов](INTERFACES.md); их названия не означают наличие одноимённых самостоятельных JSON Schema в пакете.

<a id="gsd-section-002"></a>

## 2. Объекты и смысловые связи

| Объект | Назначение | Необходимая связь |
|---|---|---|
| Context | Смысл, область, стандарт и использование | Все существенные утверждения и операции имеют определённый C |
| Source | Происхождение, доступность и цепь преобразований | Первичный адрес, версия, общий предок |
| Evidence | Конкретный полученный материал | Source, фрагмент, время, режим регистрации и Context |
| Claim | P.T.J(V,A,R).S.M.C | Основания, источники, проверки и смысловая область |
| Relation | Типизированная связь | Концы связи, собственный Claim, контекст и время |
| Model | Организация объяснения или предсказания | Утверждения, связи, метод, допущения, предел и состояние использования |
| Genesis | Историческая проекция объекта | Предметное определение оси, следы событий и неизвестные вопросы |
| Position | Положение по конкретным осям | Модель, контекст, основание ранга и условие пересмотра |
| Test | Проверяемый вопрос и различающие исходы | Конкуренты, пригодность метода, цена/риск, право и результат |
| Review | Контрольная проверка | Цель, версия, контекст, зависимости, критерий и вердикт |
| Artifact | Адресуемый продукт | Утверждения, свидетельства, результаты смысловых операций и ограничения |
| Application | Применение предметного элемента | Точное определение, цель, локальное обязательство и ProcedureRun |
| ProcedureRun | Факт выполнения процедуры | Целевые версии, входы, собственные выходы и постусловие |
| ActionProposal | Точная предлагаемая операция | Объект и версия, параметры, адресат, срок и ожидаемое постусловие |
| Authority | Проверенное право | Субъект, область, операция, период, источник и предложение |
| ActionReview | Допуск конкретного действия | Decision, ActionProposal, отпечаток, зависимости и барьеры |
| Decision | Принятый выбор | Критерий, основания, предложение, полномочие, исполнитель и статус |
| Residual | Содержательный остаток | Влияние, владелец, следующий шаг и условие пересмотра |

Связь с записью хранится адресно. Повтор текста не создаёт независимого доказательства; ссылка на запись без версии не обеспечивает актуальность. Существенная причинная, измерительная или нормативная связь также требует собственного утверждения и основания.

<a id="gsd-section-003"></a>

## 3. Claim и независимые координаты

P задаёт один тезис. T разделяет условие истинности, метод, критерии и фактический исход. J предъявляет переход от основания к P и содержит независимые результаты V/A/R. S восстанавливает происхождение. M ограничивает силу и использование. C определяет смысл и область.

Обязательная координата V/A/R имеет состояние `pass`, `fail`, `unknown` либо обоснованное `not_applicable`, адрес основания, объяснение и ограничения. Одна успешная координата не компенсирует другую. Принятое исключение в проверке допуска не изменяет этих значений автоматически.

Формальная, эмпирическая и нормативная проверка используют разные типы оснований. План измерения не является Evidence результата. Недоступность материала не означает отсутствие события. Устаревший результат ограничивает применение, но не доказывает ложность P.

<a id="gsd-section-004"></a>

## 4. Состояния и области применения

Состояния принадлежат своему типу. Нельзя переносить `pass` из Review в M как доказанную причинность или из ProcedureRun в Decision как разрешение на исполнение. Возможность, вероятность, прогноз, норма и рекомендация различаются.

Жизненный цикл кандидата отделён от предметной оценки: `withdrawn` исключает из активного поля, но не является `refuted`. Устаревание основания сохраняет его происхождение и снимает только зависимое актуальное использование.

Режим запуска `analysis_only` обозначает локальный анализ в общем договоре; `local_analysis` — класс эффекта. Поле `context.intended_use` в схеме принимает собственные значения: `discovery`, `comparison`, `recommendation`, `authorized_execution`. Это разные поля; значения не подставляются друг вместо друга. Первые два вида контекста обслуживают локальную аналитическую работу, а не разрешают внешний эффект.

Состояния результата процедуры, целого случая, передачи, утверждения и внешней операции проверяются по отдельным договорам. Ограниченный результат требует явного принятия ограничения зависимым потребителем.

<a id="gsd-section-005"></a>

## 5. Идентичность и целостность

Идентификатор однозначно связывает типизированную запись. Один ID с разным содержимым недопустим без явной версионной связи. Входные ID сохраняются, включая не использованные в выводе; новый вывод не перезаписывает исходную запись.

Версии и отпечатки связывают проверку с точной целью, C и существенными зависимостями. Изменение одной из необходимых связей требует пересмотра затронутого применения. Независимая цепочка поддержки сохраняется отдельно.

Проверка JSON Schema дополняется проверкой разрешимости ссылок, идентичности, актуальности, типа результата, роли свидетельства, жизненного цикла, бюджета и полномочий. Контрольная сумма не является доказательством авторства, полноты реестра или истинности содержания.

<a id="gsd-section-006"></a>

## 6. Обязательные поля схемы случая

Таблицы перечисляют обязательные поля типов из `case.schema.json`. Допустимые значения, вложенная структура, численные ограничения и правила дополнительных свойств берутся непосредственно из схемы. Наличие поля не отменяет требования к его содержанию и межобъектной связи.

### interval

Обязательные поля: `start`, `end`, `timezone`, `resolution`.

### context

Обязательные поля: `id`, `version`, `semantic_context`, `object_scope`, `population`, `environment`, `regime`, `time_scope`, `epistemic_standard`, `required_dimensions`, `intended_use`, `expires_at`, `reopen_trigger`, `standard_source_ids`.

| Поле | Допустимые значения |
|---|---|
| `intended_use` | `discovery`, `comparison`, `recommendation`, `authorized_execution` |

### source

Обязательные поля: `id`, `kind`, `locator`, `version`, `retrieved_at`, `origin_group`, `derived_from`, `availability`, `verification_status`, `content_hash`.

| Поле | Допустимые значения |
|---|---|
| `kind` | `file`, `web`, `measurement`, `testimony`, `model`, `formal`, `policy`, `synthetic` |
| `availability` | `available`, `unavailable`, `quarantined` |
| `verification_status` | `unverified`, `checked`, `retracted` |

### evidence

Обязательные поля: `id`, `source_id`, `locator`, `content`, `mode`, `observation_state`, `context_id`, `observed_at`, `transformation`, `version`.

| Поле | Допустимые значения |
|---|---|
| `mode` | `direct`, `derived`, `testimony`, `model`, `synthetic` |
| `observation_state` | `observed`, `not_measured`, `missing`, `below_detection`, `withheld`, `corrupted`, `unknown` |

### assessment

Обязательные поля: `state`, `basis_evidence_ids`, `explanation`, `limitations`, `required_for_use`.

| Поле | Допустимые значения |
|---|---|
| `state` | `pass`, `fail`, `unknown`, `not_applicable` |

### probability

Обязательные поля: `lower`, `upper`, `model_id`, `method`, `basis_evidence_ids`, `conditional_scope`.

### verification

Обязательные поля: `method`, `acceptance_criterion`, `rejection_criterion`, `inconclusive_condition`, `invalid_condition`, `status`, `outcome`, `result_evidence_ids`.

| Поле | Допустимые значения |
|---|---|
| `status` | `unplanned`, `planned`, `running`, `completed`, `invalid`, `stale` |

### claim

Обязательные поля: `id`, `version`, `P`, `T`, `J`, `S`, `M`, `C`.

### relation

Обязательные поля: `id`, `from_id`, `to_id`, `type`, `claim_id`, `context_id`, `temporal_lag`, `status`, `version`.

| Поле | Допустимые значения |
|---|---|
| `type` | `supports`, `refutes`, `undercuts`, `causes`, `associated`, `part_of`, `precedes`, `compensates`, `modifies`, `common_parent`, `derived_from`, `interaction`, `syndrome_member`, `indicates` |
| `status` | `candidate`, `supported`, `contested` |

### model

Обязательные поля: `id`, `kind`, `context_id`, `claim_ids`, `relation_ids`, `assumptions`, `limits`, `identification_status`, `version`, `method_contract`, `assertion_claim_id`, `assessment_review_id`, `use_state`.

| Поле | Допустимые значения |
|---|---|
| `kind` | `tree`, `dag`, `dynamic`, `association`, `factor`, `probability`, `mixed`, `genesis` |
| `identification_status` | `unassessed`, `candidate`, `identified_within_scope`, `underdetermined` |
| `use_state` | `active`, `requires_review`, `blocked` |

### position

Обязательные поля: `claim_id`, `model_id`, `context_id`, `explanatory`, `structural_measure`, `evidential`, `prevalence`, `disciplinary_acceptance`, `frame_distance`, `miss_risk`, `test_value`, `basis_claim_ids`, `revision_trigger`.

| Поле | Допустимые значения |
|---|---|
| `explanatory` | `central`, `peripheral`, `marginal`, `unknown` |

### genesis

Обязательные поля: `id`, `context_id`, `axis`, `domain_definition`, `mapping_status`, `claim_ids`, `event_evidence_ids`, `unresolved_questions`, `version`.

| Поле | Допустимые значения |
|---|---|
| `axis` | `phylogeny`, `ontogeny`, `morphogenesis`, `epigenesis`, `etiology`, `defect_development`, `resource_development`, `function_development`, `decay`, `regeneration`, `coevolution`, `measurement_history`, `microgenesis`, `technogenesis`, `organizational_genesis` |
| `mapping_status` | `domain_native`, `explicit_analogy`, `not_applicable` |

### test

Обязательные поля: `id`, `question_claim_id`, `competitor_claim_ids`, `method`, `outcome_rules`, `applicability_claim_id`, `cost_risk_claim_id`, `authority_id`, `status`, `result_evidence_ids`, `version`, `use_state`.

| Поле | Допустимые значения |
|---|---|
| `status` | `planned`, `requested`, `running`, `completed`, `invalid`, `cancelled` |
| `use_state` | `active`, `requires_review`, `blocked` |

### authority

Обязательные поля: `id`, `owner`, `scope`, `operation_id`, `context_id`, `verification`, `verification_evidence_ids`, `valid_until`, `policy_source_ids`, `verifier`, `version`, `valid_from`, `proposal_digest`, `use_state`.

| Поле | Допустимые значения |
|---|---|
| `verification` | `unverified`, `externally_verified`, `revoked` |
| `use_state` | `active`, `requires_review`, `blocked` |

### waiver

Обязательные поля: `original_verdict`, `authority_id`, `expires_at`, `scope`, `policy_evidence_ids`, `compensating_claim_ids`.

| Поле | Допустимые значения |
|---|---|
| `original_verdict` | `soft_fail`, `hard_fail` |

### review

Обязательные поля: `id`, `gate`, `target_claim_id`, `execution_state`, `verdict`, `criterion`, `evidence_ids`, `limitations`, `waiver`, `version`, `binding`, `lifecycle`, `supersedes_ids`.

| Поле | Допустимые значения |
|---|---|
| `gate` | `G01`, `G02`, `G03`, `G04`, `G05`, `G06`, `G07`, `G08`, `PTJSMC`, `TRANSPORT`, `INDEPENDENCE`, `SAFETY` |
| `execution_state` | `not_started`, `running`, `completed`, `not_applicable`, `insufficient_data` |
| `lifecycle` | `active`, `stale`, `superseded` |

### artifact

Обязательные поля: `id`, `kind`, `context_id`, `summary`, `claim_ids`, `evidence_ids`, `limitations`, `version`, `input_fingerprint`, `semantic_result_refs`, `accepted_limitations_by`.

| Поле | Допустимые значения |
|---|---|
| `kind` | `ActionOptions`, `ActiveHypotheses`, `AdversarialSet`, `AlternativeTrajectory`, `AnalogyCandidate`, `ArgumentReview`, `AssumptionAlternative`, `AuthorityReview`, `BoundaryHypothesis`, `C`, `CausalModel`, `ChangeReview`, `Claim сигнала`, `Claim симптома`, `ClaimAdmissibilityReview`, `ClosureRecord`, `ClusteredSet`, `CommitReview`, `CompensationReview`, `ConflictRecord`, `CriticalClaimReview`, `CrossLevelReview`, `DecisionComparison`, `Diagnosis`, `DifferentialSummary`, `DirectionAlternatives`, `Discriminator`, `DynamicModel`, `EffectReview`, `ElementRole`, `EpigenesisClaim`, `EtiologyMap`, `Evidence`, `EvidenceMatrix`, `ExecutionClaim`, `ExecutionPreflight`, `ExecutionReceipt`, `ExplanatoryResidual`, `FactorModel`, `FailureRecord`, `FrameSet`, `G01 Review`, `G02 Review`, `G03 Review`, `G04 Review`, `G05 Review и Decision`, `G06 Review`, `G07 Review`, `G08 Review`, `GenesisIntegration`, `GenesisMap`, `GraphReview`, `HandoffRecord`, `HazardPriority`, `HazardRegister`, `HistoricalHypothesis`, `HypothesisSet`, `HysteresisClaim`, `IdentifiabilityReview`, `IdentificationBoundary`, `IndependentReviewContract`, `InjectionRecord`, `InteractionModel`, `InvalidationSet`, `J.A`, `J.R`, `J.V`, `J.inference_rule`, `J.premise_refs и evidence_refs`, `JointHypothesis`, `LearningChange`, `M.epistemic_status`, `M.evidence_state`, `M.modality`, `MonitoringPlan`, `MorphogenesisClaim`, `NegativeEvidenceReview`, `NullAndMeasurementSet`, `ObservationModel`, `OntogenyClaim`, `OutcomeClaim`, `OutputReview`, `P`, `PhylogenyClaim`, `PositionVector`, `PredictiveClaim`, `ProbabilityModel`, `ProtectionReview`, `ReconciliationRecord`, `RecoveryReview`, `ReleaseDecision`, `ReliabilityReview`, `ReopenRecord`, `RepresentationAlternative`, `ResidualSet`, `ResourceGenesisClaim`, `ResourceSet`, `RetirementRecord`, `Review синдрома`, `Review целостности атома`, `RiskAcceptanceReview`, `S`, `SafetyCase`, `SelectedTest`, `SensitivityReview`, `Source`, `SourceApplicationContract`, `SourceApplicationReview`, `SourceConflict`, `SourceElement`, `StatisticalReview`, `SyndromeModel`, `T.truth_condition`, `T.truthmaker_candidate`, `T.verification`, `TestCostRisk`, `TestPlan`, `TestQuestion`, `TestRequestOrReceipt`, `TestResult`, `TestValidityReview`, `Timeline`, `TransportReview`, `TypedGraph`, `UnderdeterminationSet`, `WaiverReview`, `Атомы и композиция`, `Временная карта`, `Граф отношений`, `Граф происхождения`, `Запись восстановления`, `Запись комплектации`, `Запись срочности`, `Запись цикла`, `Идентификация объекта`, `Карта возможностей`, `Карта доверия`, `Карта уровней`, `Контекст C`, `Контекстуальный стандарт`, `Корневой вопрос`, `Модель получения данных`, `Норма`, `Нормализованный Evidence`, `Политика остановки`, `Профиль исполнения`, `Профиль риска`, `Реестр пропусков`, `Ролевая граница`, `Сверка объекта`, `Состояние пригодности Evidence`, `Типизированный P` |

### residual

Обязательные поля: `content`, `impact`, `owner_or_unassigned`, `next_step`, `reopen_trigger`.

### application

Обязательные поля: `id`, `source_element_key`, `source_hash`, `exact_text`, `target_claim_ids`, `procedure_id`, `role`, `local_obligation`, `input_refs`, `expected_output`, `counterexample`, `status`, `result_artifact_ids`, `reason`, `version`, `run_id`, `target_versions`.

| Поле | Допустимые значения |
|---|---|
| `procedure_id` | `BOOT.01`, `BOOT.02`, `BOOT.03`, `BOOT.04`, `BOOT.05`, `BOOT.06`, `CONTRACT.01`, `CONTRACT.02`, `CONTRACT.03`, `CONTRACT.04`, `CONTRACT.05`, `CONTRACT.06`, `CONTRACT.07`, `CONTRACT.08`, `CONTRACT.09`, `INGEST.01`, `INGEST.02`, `INGEST.03`, `INGEST.04`, `INGEST.05`, `INGEST.06`, `INGEST.07`, `INGEST.08`, `INGEST.09`, `ATOM.01`, `ATOM.02`, `ATOM.03`, `ATOM.04`, `ATOM.05`, `ATOM.06`, `ATOM.07`, `ATOM.08`, `ATOM.09`, `ATOM.10`, `ATOM.11`, `ATOM.12`, `ATOM.13`, `ATOM.14`, `ATOM.15`, `ATOM.16`, `ATOM.17`, `ATOM.18`, `STRUCTURE.01`, `STRUCTURE.02`, `STRUCTURE.03`, `STRUCTURE.04`, `STRUCTURE.05`, `STRUCTURE.06`, `STRUCTURE.07`, `STRUCTURE.08`, `STRUCTURE.09`, `STRUCTURE.10`, `STRUCTURE.11`, `GENESIS.01`, `GENESIS.02`, `GENESIS.03`, `GENESIS.04`, `GENESIS.05`, `GENESIS.06`, `GENESIS.07`, `GENESIS.08`, `GENESIS.09`, `GENESIS.10`, `GENESIS.11`, `GENERATE.01`, `GENERATE.02`, `GENERATE.03`, `GENERATE.04`, `GENERATE.05`, `GENERATE.06`, `GENERATE.07`, `GENERATE.08`, `GENERATE.09`, `GENERATE.10`, `GENERATE.11`, `GENERATE.12`, `GENERATE.13`, `GENERATE.14`, `MODEL.01`, `MODEL.02`, `MODEL.03`, `MODEL.04`, `MODEL.05`, `MODEL.06`, `MODEL.07`, `MODEL.08`, `VERIFY.01`, `VERIFY.02`, `VERIFY.03`, `VERIFY.04`, `VERIFY.05`, `VERIFY.06`, `VERIFY.07`, `VERIFY.08`, `VERIFY.09`, `VERIFY.10`, `VERIFY.11`, `VERIFY.12`, `VERIFY.13`, `VERIFY.14`, `COMPARE.01`, `COMPARE.02`, `COMPARE.03`, `COMPARE.04`, `COMPARE.05`, `COMPARE.06`, `COMPARE.07`, `TEST.01`, `TEST.02`, `TEST.03`, `TEST.04`, `TEST.05`, `TEST.06`, `TEST.07`, `SYNTHESIS.01`, `SYNTHESIS.02`, `SYNTHESIS.03`, `SYNTHESIS.04`, `SYNTHESIS.05`, `DECISION.01`, `DECISION.02`, `DECISION.03`, `DECISION.04`, `DECISION.05`, `DECISION.06`, `DECISION.07`, `MONITOR.01`, `MONITOR.02`, `MONITOR.03`, `MONITOR.04`, `MONITOR.05`, `MONITOR.06`, `MONITOR.07`, `ASSURANCE.01`, `ASSURANCE.02`, `ASSURANCE.03`, `ASSURANCE.04`, `ASSURANCE.05`, `ASSURANCE.06`, `ASSURANCE.07`, `ASSURANCE.08`, `CORPUS.01`, `CORPUS.02`, `CORPUS.03`, `CORPUS.04`, `CORPUS.05`, `LIFECYCLE.01`, `LIFECYCLE.02`, `LIFECYCLE.03`, `LIFECYCLE.04`, `LIFECYCLE.05`, `LIFECYCLE.06` |
| `role` | `distinction`, `generation`, `method`, `quality`, `domain_policy`, `reference` |
| `status` | `imported`, `read`, `routed`, `applied`, `not_applicable`, `deferred`, `source_conflict` |

### decision

Обязательные поля: `id`, `selected_operation_id`, `basis_claim_ids`, `authority_id`, `status`, `context_id`, `criterion`, `executor`, `idempotency_key`, `reopen_trigger`, `execution_evidence_ids`, `version`, `proposal_id`, `use_state`.

| Поле | Допустимые значения |
|---|---|
| `status` | `recommendation`, `authorized`, `sent`, `executed`, `outcome_unknown`, `cancelled` |
| `use_state` | `active`, `requires_review`, `blocked` |
| `imported_original_status` | `recommendation`, `authorized`, `sent`, `executed`, `outcome_unknown`, `cancelled` |

### case

Обязательные поля: `case_id`, `version`, `revision`, `data_kind`, `requested_profile`, `risk`, `contract`, `contexts`, `sources`, `evidence`, `claims`, `relations`, `models`, `positions`, `genesis`, `tests`, `authorities`, `reviews`, `artifacts`, `source_applications`, `decisions`, `residuals`, `status`, `action_proposals`, `action_reviews`, `procedure_runs`.

| Поле | Допустимые значения |
|---|---|
| `data_kind` | `real`, `synthetic` |
| `requested_profile` | `eMVP`, `MVP`, `Standard`, `eStandard`, `High Stakes`, `Critical Infrastructure` |
| `status` | `new`, `active`, `awaiting_evidence`, `awaiting_authority`, `degraded`, `partial`, `ready_for_review`, `closed`, `reopened`, `blocked` |

### binding

Обязательные поля: `target_version`, `target_digest`, `context_version`, `context_digest`, `dependency_fingerprint`.

### budget

Обязательные поля: `step_limit`, `reserve_steps`, `cost_limit`, `deadline`.

### action_proposal

Обязательные поля: `id`, `version`, `operation_id`, `target_id`, `target_version`, `parameters`, `context_id`, `recipient`, `expected_postcondition`, `reversibility`, `expires_at`.

| Поле | Допустимые значения |
|---|---|
| `reversibility` | `reversible`, `costly`, `irreversible`, `unknown` |

### action_review

Обязательные поля: `id`, `version`, `decision_id`, `proposal_id`, `proposal_digest`, `context_id`, `gate`, `verdict`, `evidence_ids`, `expires_at`, `dependency_fingerprint`, `lifecycle`, `supersedes_ids`, `scope`, `allow_provisional_basis`, `provisional_rationale`.

| Поле | Допустимые значения |
|---|---|
| `gate` | `G05`, `G07`, `G08`, `SAFETY`, `INDEPENDENCE` |
| `verdict` | `pass`, `soft_fail`, `hard_fail`, `kill_fail` |
| `lifecycle` | `active`, `stale`, `superseded` |

### method_contract

Обязательные поля: `variables`, `estimand`, `method`, `identification_argument`, `parameter_evidence_ids`, `assumptions`, `validation_limit`.

### run_record

Обязательные поля: `id`, `version`, `procedure_id`, `target_claim_ids`, `target_bindings`, `input_refs`, `dependency_fingerprint`, `output_ids`, `status`, `postcondition`, `limitations`, `input_revision`.

| Поле | Допустимые значения |
|---|---|
| `status` | `pass`, `limited` |

<a id="gsd-section-007"></a>

## 7. Реестры определений

`data/procedures.json` содержит 152 договора детальных процедур. `data/component_contracts.json` содержит 37 протоколов G/S/D. `data/semantic_leaves.json` задаёт 31 самостоятельный результат составных шагов. `data/element_index.json` указывает документ, строку, раздел, роль и определение именованного элемента.

Эти реестры являются определениями. Они не свидетельствуют о выполнении процедуры, прохождении проверки, применении принципа или принятии внешнего действия. Для этого создаются конкретные записи исполнения и основания результатов.
