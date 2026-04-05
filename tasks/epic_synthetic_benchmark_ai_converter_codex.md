
# Epic и разбиение на задачи для Codex: модуль генерации синтетических датасетов для оценки `ai-convertor` (`JSON L0 -> L1`)

## Что это за документ

Ниже — **epic** и его разбиение на **5 автономных задач** в формате, удобном для постановки в Codex.

Документ рассчитан на реализацию **отдельного модуля системы**, который отвечает не за сам `ai-convertor`, а за **генерацию синтетических датасетов, генерацию drift-сценариев, запуск воспроизводимого benchmark pipeline и сбор метрик** для оценки качества `ai-convertor` на всех этапах работы.

---

## Ключевая идея компонента

Чтобы синтетические данные были одновременно:

- разнообразными,
- воспроизводимыми,
- пригодными для unit/integration тестов,
- совместимыми с gold-оценкой качества преобразования,

нужно строить генерацию не напрямую как «LLM придумывает произвольный `L0` и `L1`», а через **внутреннее каноническое семантическое представление**.

### Рекомендуемая внутренняя схема артефактов

```text
CanonicalScenario
    -> deterministic L1 renderer
    -> deterministic L0 template renderer
    -> drift mutators
    -> benchmark bundle
```

Где:

- `CanonicalScenario` — внутренняя каноническая семантика сущностей и связей;
- `L1` — gold target, детерминированно строится из `CanonicalScenario`;
- `L0TemplateSpec` — описание того, как эту же семантику «упаковать» в `JSON L0`;
- `L0` — конкретный JSON-экземпляр, порожденный из `CanonicalScenario` + `L0TemplateSpec`;
- `DriftSpec` — описание контролируемых изменений структуры `L0`;
- `DatasetBundle` — сохраненный артефакт эксперимента (`scenario`, `l0`, `l1`, manifests, metadata).

### Почему это важно

Такой дизайн позволяет:

1. иметь **всегда корректный gold `L1`**;
2. делать **seeded deterministic generation** без LLM;
3. использовать LLM **только для генерации новых `L0`-шаблонов / surface forms**, а не для произвольного изобретения истины;
4. отдельно тестировать:
   - семантику сценария,
   - генерацию `L0`,
   - drift,
   - benchmark harness,
   - сбор метрик.

---

## Назначение epic

Построить модуль `synthetic_benchmark`, который:

1. генерирует пары `L0/L1` без LLM;
2. генерирует более разнообразные `L0` с помощью LLM;
3. поддерживает **неконсистентность однотипных подобъектов** по составу полей;
4. генерирует **drifted `L0`** для проверки устойчивости `ai-convertor`;
5. сохраняет все артефакты для воспроизводимости;
6. запускает **benchmark pipeline** для оценки `ai-convertor`;
7. умеет фиксировать `N` — число независимых запусков `ai-convertor` для оценки стабильности и построения boxplots;
8. собирает stage-wise и end-to-end метрики.

---

## Scope epic

### Входит в epic

- отдельный модуль системы для синтетических данных и benchmark;
- deterministic generator;
- LLM-assisted generator;
- drift generator;
- артефактное хранение датасетов и запусков;
- benchmark harness;
- метрики, агрегация, отчеты и boxplots;
- CLI / entry points;
- документация и обновление `AGENTS.md`.

### Не входит в epic

- реализация самого `ai-convertor`;
- обучение/finetuning отдельных моделей;
- production-оркестрация внешних LLM-сервисов;
- большие distributed pipelines;
- live LLM calls в unit tests.

---

## Функциональные требования

### FR-1. Deterministic generator

Должен существовать генератор без LLM, который по конфигурации и seed:

- строит `CanonicalScenario`;
- строит gold `L1`;
- строит один или несколько `L0`;
- допускает разную упаковку одной и той же семантики в `L0`;
- воспроизводим при одинаковом `seed + config + version`.

### FR-2. LLM-assisted generator

Должен существовать отдельный генератор, который использует LLM для получения **более разнообразных `L0TemplateSpec`** или их patch-вариантов.

Ключевое ограничение:

- LLM не должен быть единственным источником ground truth;
- gold `L1` должен оставаться детерминированным и трассируемым к `CanonicalScenario`.

### FR-3. Heterogeneous subobjects

Генератор должен уметь создавать `JSON`, в котором объекты одного логического типа имеют разный состав полей, например:

- у части объектов есть расширенные поля;
- у части полей нет;
- у части есть vendor-specific extras;
- у части структура вложенности отличается в допустимых пределах.

### FR-4. Drift generation

Компонент должен уметь генерировать новые `L0` для проверки гибкости `ai-convertor` к drift, включая как минимум:

- additive drift;
- rename drift;
- nesting drift;
- sparsity drift;
- enum/value format drift;
- split/merge field drift;
- heterogeneous-object drift.

### FR-5. Benchmark pipeline

Компонент должен включать полный pipeline эксперимента:

1. генерация base `L0/L1`;
2. генерация drifted `L0`;
3. сохранение bundles;
4. запуск `ai-convertor`;
5. повторение запуска `N` раз;
6. сбор stage-wise и final metrics;
7. построение агрегированных отчетов и boxplots.

### FR-6. Reproducibility

Должны сохраняться:

- конфигурации генерации;
- seed для deterministic generator;
- manifests каждого bundle;
- версии шаблонов;
- LLM prompt/response cache или сохраненные accepted templates;
- результаты benchmark runs;
- итоговые metrics/reports.

### FR-7. Isolation and testability

Каждый крупный модуль должен быть тестируем отдельно unit tests без live network/LLM calls.

---

## Нефункциональные требования

- Python 3.11+.
- Предпочитать существующий стек репозитория.
- Минимизировать новые зависимости.
- Все публичные функции и классы — с type hints и docstrings.
- Каждый новый Python-файл — с module docstring в начале.
- Все команды запуска и структура репозитория должны быть отражены в `README.md` и `AGENTS.md`.
- Unit tests должны запускаться локально без внешних сервисов.
- Экспериментальные артефакты должны иметь стабильную структуру каталогов.

---

## Базовая архитектура модуля

```text
repo/
├─ AGENTS.md
├─ README.md
├─ docs/
│  ├─ synthetic_benchmark/
│  │  ├─ architecture.md
│  │  ├─ generators.md
│  │  ├─ drift.md
│  │  ├─ benchmark.md
│  │  └─ metrics.md
├─ configs/
│  ├─ synthetic_benchmark/
│  │  ├─ deterministic/
│  │  ├─ llm/
│  │  └─ benchmark/
├─ src/
│  ├─ ai_converter/                  # существующий модуль, если уже есть
│  └─ synthetic_benchmark/
│     ├─ __init__.py
│     ├─ scenario/
│     ├─ templates/
│     ├─ generators/
│     │  ├─ deterministic/
│     │  └─ llm/
│     ├─ renderers/
│     ├─ drift/
│     ├─ storage/
│     ├─ benchmark/
│     ├─ metrics/
│     ├─ reports/
│     └─ cli/
└─ tests/
   ├─ unit/
   │  └─ synthetic_benchmark/
   ├─ integration/
   │  └─ synthetic_benchmark/
   └─ fixtures/
      └─ synthetic_benchmark/
```

Если в репозитории уже есть иная структура, нужно сохранить логику модулей, но аккуратно адаптировать пути.

---

## Основные модели данных

### `CanonicalScenario`

Внутреннее каноническое описание содержимого, независимое от формы `L0`.

Примерный состав:

- список логических сущностей;
- идентификаторы;
- значения полей;
- связи между сущностями;
- опциональные атрибуты;
- ограничения и инварианты.

### `L0TemplateSpec`

Описание surface-формы `L0`:

- имена полей и алиасы;
- правила вложенности;
- правила flatten/nest;
- правила split/merge;
- объектные shape-variants;
- правила шумовых полей;
- правила sparsity;
- допустимые heterogeneous subobjects.

### `DriftSpec`

Описание управляемого drift-сценария:

- тип drift;
- severity;
- применимость;
- ожидаемая совместимость;
- lineage к базовому template/bundle.

### `DatasetBundle`

Сохраняемый артефакт одного примера:

- `bundle_id`;
- `scenario.json`;
- `template.json`;
- `l0.json`;
- `l1.json`;
- `source_oracle.json`;
- `drift_manifest.json` (если есть);
- `metadata.json`.

---

## Рекомендуемые метрики

Компонент должен собирать **не одну метрику**, а несколько групп метрик.

### 1. Метрики этапа построения конвертера

Если `ai-convertor` отдает промежуточные артефакты, собирать:

- качество восстановления структуры источника;
- точность/полноту path-level соответствий;
- качество mapping-плана;
- число repair-итераций;
- build success rate;
- build time.

### 2. Метрики выполнения конвертера

- доля успешно обработанных `L0`;
- доля `L1`, проходящих валидацию;
- runtime errors;
- latency.

### 3. Метрики semantic correctness

- exact match на уровне целевого JSON, если допустимо;
- field-level precision / recall / F1;
- обязательные поля: hit rate;
- numeric tolerance metrics;
- enum accuracy;
- tree-diff / normalized JSON diff.

### 4. Метрики устойчивости к drift

- degradation относительно base;
- success rate per drift class;
- semantic score per drift class and severity.

### 5. Метрики стабильности

При фиксированном `N` независимых запусков `ai-convertor`:

- mean / median / std;
- IQR;
- success distribution;
- boxplot-friendly summary;
- run-to-run variance.

---

## Acceptance criteria для epic целиком

Epic считается выполненным, если одновременно выполнены все условия:

1. Есть deterministic generator, который по seed создает воспроизводимые `L0/L1` bundles.
2. Есть LLM-assisted generator, который расширяет разнообразие `L0`, но не ломает трассируемость gold `L1`.
3. Есть генерация heterogeneous subobjects.
4. Есть drift generator с несколькими классами drift.
5. Все сгенерированные samples сохраняются на диск вместе с manifests.
6. Benchmark pipeline позволяет фиксировать `N` и делать повторные запуски `ai-convertor`.
7. Метрики сохраняются в машиночитаемом виде.
8. Генерируются summary reports и boxplots.
9. Unit tests проходят без live LLM/network calls.
10. `README.md`, `AGENTS.md` и docs обновлены.

---

## Зависимости между задачами

- **TASK-01** — канонические модели, deterministic generator, deterministic renderers, persistence.
- **TASK-02** — heterogeneous subobjects и drift framework.
- **TASK-03** — LLM-assisted template generation и cache/validation.
- **TASK-04** — benchmark harness, adapter к `ai-convertor`, stage-wise metrics.
- **TASK-05** — reports, CLI, experiment UX, end-to-end smoke coverage.

Рекомендуемый порядок: `TASK-01 -> TASK-02 -> TASK-03 -> TASK-04 -> TASK-05`.

---

# TASK-01. Канонические модели, deterministic generator, deterministic renderers и сохранение bundles

## Goal

Построить основу модуля `synthetic_benchmark`: канонические модели, seeded deterministic generation, deterministic renderers для `L0` и `L1`, а также сохранение bundle-артефактов на диск.

## Context

Без этой задачи нельзя обеспечить ни gold `L1`, ни воспроизводимость, ни изолированное тестирование других компонентов.

Ключевое архитектурное решение этой задачи: **истина хранится в `CanonicalScenario`, а `L0` и `L1` являются разными отображениями этой истины**.

## Scope

Нужно реализовать:

1. `CanonicalScenario` и связанные модели.
2. `L0TemplateSpec` базового уровня.
3. Seeded deterministic sampler сценариев.
4. Deterministic renderer `CanonicalScenario -> L1`.
5. Deterministic renderer `CanonicalScenario + L0TemplateSpec -> L0`.
6. Формат `DatasetBundle`.
7. Сохранение и загрузку bundles.
8. Фиксацию reproducibility metadata.

Не нужно в рамках задачи:

- использовать LLM;
- делать drift;
- строить benchmark pipeline;
- генерировать charts.

## Deliverables

Минимальный набор артефактов:

- `src/synthetic_benchmark/scenario/models.py`
- `src/synthetic_benchmark/templates/models.py`
- `src/synthetic_benchmark/generators/deterministic/scenario_sampler.py`
- `src/synthetic_benchmark/renderers/l1_renderer.py`
- `src/synthetic_benchmark/renderers/l0_renderer.py`
- `src/synthetic_benchmark/storage/bundle_store.py`
- `src/synthetic_benchmark/storage/models.py`
- `tests/unit/synthetic_benchmark/scenario/`
- `tests/unit/synthetic_benchmark/renderers/`
- `tests/fixtures/synthetic_benchmark/bundles/`
- `docs/synthetic_benchmark/architecture.md`

## Алгоритмика

### 1. Канонический слой

Определить `CanonicalScenario` как нормализованный graph-like объект:

- сущности с `entity_id`;
- logical types;
- поля и значения;
- связи и ссылки;
- опциональные свойства;
- внутренние инварианты.

### 2. Seeded deterministic sampling

Сэмплировать сценарий только через фиксированный RNG:

- `random.Random(seed)` или эквивалент;
- все случайные решения получать из одного контролируемого источника;
- в metadata сохранять `seed`, `generator_version`, `config_hash`.

### 3. Deterministic `L1` rendering

`L1` должен строиться детерминированно из `CanonicalScenario`, предпочтительно через существующие `Pydantic`-модели целевого слоя, если они уже есть в проекте.

Если в проекте есть готовые `L1`-модели, повторно использовать их, а не дублировать.

### 4. Deterministic `L0` rendering

`L0TemplateSpec` должен задавать:

- алиасы имен полей;
- варианты упаковки в nested JSON;
- базовые optional masks;
- правила списков и подобъектов;
- базовые extra/noise поля.

### 5. Bundle storage

Каждый bundle сохранять как отдельную директорию:

```text
artifacts/synthetic_benchmark/datasets/<dataset_id>/<bundle_id>/
├─ scenario.json
├─ template.json
├─ l0.json
├─ l1.json
└─ metadata.json
```

### 6. Reproducibility contract

Metadata должны содержать минимум:

- `bundle_id`;
- `dataset_id`;
- `seed`;
- `generator_version`;
- `config_hash`;
- `created_at`;
- `source_template_id`.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- `orjson` или stdlib `json`
- stdlib `random`, `pathlib`, `hashlib`, `uuid`
- `pytest`
- `hypothesis` для property-based tests reproducibility

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_same_seed_produces_same_canonical_scenario`
2. `test_different_seeds_produce_different_scenarios`
3. `test_l1_renderer_output_passes_target_validation`
4. `test_l0_renderer_preserves_core_semantics`
5. `test_bundle_store_roundtrip_is_lossless`
6. `test_metadata_contains_reproducibility_fields`

Желательные тесты:

- property test на стабильность bundle serialization;
- snapshot test на небольшой пример bundle.

## Done when / Acceptance criteria

Задача завершена, если:

- deterministic sampler реализован;
- `L0` и `L1` генерируются из общего `CanonicalScenario`;
- bundle можно сохранить и загрузить без потерь;
- генерация воспроизводима по seed;
- unit tests проходят локально.

## Checklist

- [ ] Реализованы `CanonicalScenario`, `L0TemplateSpec`, `DatasetBundle`.
- [ ] Добавлены deterministic renderers для `L0` и `L1`.
- [ ] Реализовано сохранение/загрузка bundle-артефактов.
- [ ] Добавлены unit tests и фикстуры.
- [ ] Запущены тесты (`pytest` или проектная команда тестов).
- [ ] Обновлен `README.md` с описанием deterministic generator.
- [ ] Обновлен `AGENTS.md`: новая структура модуля, команды тестов, расположение artifacts.
- [ ] Проверено, что у всех новых публичных сущностей есть type hints и docstrings.
- [ ] Проверено, что в начале каждого нового Python-файла есть module docstring.
- [ ] Обновлена схема репозитория в `AGENTS.md` и/или docs.

---

# TASK-02. Генерация heterogeneous subobjects и framework для drift-сценариев

## Goal

Добавить в синтетический генератор поддержку:

1. неконсистентных однотипных подобъектов;
2. контролируемого drift в `L0`;
3. lineage между base и drifted bundles.

## Context

Эта задача делает данные полезными для тестирования реального `ai-convertor`, который должен сталкиваться не только с чистыми JSON, но и с частично неоднородными структурами и изменениями формата.

## Scope

Нужно реализовать:

1. shape-variant policies для однотипных объектов;
2. генерацию heterogeneous arrays/objects;
3. `DriftSpec`;
4. набор drift operators;
5. lineage/base->drift manifests;
6. сохранение drift bundles.

Не нужно:

- использовать LLM;
- запускать benchmark;
- строить boxplots.

## Deliverables

- `src/synthetic_benchmark/templates/shape_variants.py`
- `src/synthetic_benchmark/drift/models.py`
- `src/synthetic_benchmark/drift/operators.py`
- `src/synthetic_benchmark/drift/apply.py`
- `src/synthetic_benchmark/storage/lineage.py`
- `tests/unit/synthetic_benchmark/drift/`
- `tests/fixtures/synthetic_benchmark/drift/`
- `docs/synthetic_benchmark/drift.md`

## Алгоритмика

### 1. Heterogeneous subobjects

Для каждого логического object type разрешить несколько shape-вариантов:

- `core fields` — минимальный обязательный набор;
- `optional pool` — поля, которые могут появляться/исчезать;
- `rare extras` — редкие, но валидные дополнительные поля;
- `vendor extras` — дополнительные специфические поля без влияния на gold `L1`.

Каждому экземпляру объекта назначать shape-вариант детерминированно от seed.

### 2. Drift operators

Минимальный набор операторов drift:

- `add_field`
- `drop_optional_field`
- `rename_field`
- `nest_field`
- `flatten_field`
- `split_field`
- `merge_fields`
- `change_value_format`
- `change_enum_surface`
- `inject_sparse_objects`

### 3. Drift severity

Каждый drift запускать через параметр `severity`:

- `low` — слабое изменение структуры;
- `medium`;
- `high`.

Важно: drift должен менять `L0`, но не ломать трассируемость к исходному `CanonicalScenario`, если drift помечен как совместимый.

### 4. Lineage

Каждый drift bundle должен хранить связь с базовым bundle:

- `parent_bundle_id`;
- `drift_type`;
- `severity`;
- `operator_sequence`;
- `compatibility_class`.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `copy`, `json`, `pathlib`
- `pytest`
- `hypothesis` для combinatorial/property tests drift operators

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_same_logical_type_can_have_different_field_sets`
2. `test_shape_variants_are_seeded_and_reproducible`
3. `test_drift_operator_adds_expected_manifest`
4. `test_compatible_drift_preserves_gold_l1`
5. `test_high_severity_drift_changes_l0_structure`
6. `test_lineage_links_drift_bundle_to_parent`

Желательные тесты:

- property test на композицию drift operators;
- snapshot test на drift manifests.

## Done when / Acceptance criteria

Задача завершена, если:

- генератор умеет создавать heterogeneous subobjects;
- drift operators реализованы и версионируются;
- drift bundles сохраняются вместе с lineage metadata;
- unit tests проходят локально.

## Checklist

- [ ] Реализованы shape-variant policies и heterogeneous generation.
- [ ] Реализованы drift operators и `DriftSpec`.
- [ ] Сохраняются drift manifests и lineage metadata.
- [ ] Добавлены unit tests и фикстуры.
- [ ] Запущены тесты (`pytest` или проектная команда тестов).
- [ ] Обновлен `README.md` с примерами heterogeneous JSON и drift generation.
- [ ] Обновлен `AGENTS.md`: структура drift-модуля, команды запуска, расположение fixtures/artifacts.
- [ ] Проверено, что весь новый код покрыт docstrings и module docstrings.
- [ ] Обновлена структура репозитория в `AGENTS.md` и/или docs.

---

# TASK-03. LLM-assisted генерация разнообразных `L0TemplateSpec`, cache и validation gates

## Goal

Добавить второй генератор, который использует LLM для синтеза **новых шаблонов представления `L0`**, чтобы получать больше структурного разнообразия, не теряя корректный gold `L1`.

## Context

Ключевое требование: LLM используется не как единственный автор истины, а как генератор новых `L0TemplateSpec` или template patches. Инстанцирование конкретных значений и gold `L1` остается детерминированным.

## Scope

Нужно реализовать:

1. интерфейс `TemplateGenerationClient`;
2. промпт-контракты для генерации `L0TemplateSpec`;
3. validation pipeline для LLM output;
4. dry-run instantiation;
5. cache accepted templates;
6. bounded repair/retry loop;
7. сохранение prompt/response metadata или эквивалентных cache-артефактов.

Не нужно:

- использовать live LLM calls в unit tests;
- делать benchmark pipeline;
- делать финальные отчеты.

## Deliverables

- `src/synthetic_benchmark/generators/llm/models.py`
- `src/synthetic_benchmark/generators/llm/client_protocol.py`
- `src/synthetic_benchmark/generators/llm/prompt_builder.py`
- `src/synthetic_benchmark/generators/llm/validator.py`
- `src/synthetic_benchmark/generators/llm/cache.py`
- `src/synthetic_benchmark/generators/llm/generator.py`
- `tests/unit/synthetic_benchmark/generators_llm/`
- `tests/fixtures/synthetic_benchmark/llm_templates/`
- `docs/synthetic_benchmark/generators.md`

## Алгоритмика

### 1. Template-first generation

LLM должен возвращать не финальный dataset bundle, а **структурированный `L0TemplateSpec`** или `TemplatePatch`.

Это критично, потому что:

- шаблон легче валидировать;
- шаблон можно dry-run инстанцировать;
- gold `L1` по-прежнему строится детерминированно.

### 2. Validation gates

Для каждого ответа LLM проходить последовательность проверок:

1. parse JSON / structured output;
2. валидация через `Pydantic`;
3. policy validation:
   - нет запрещенных трансформаций;
   - нет потери обязательной семантики;
   - допустимый набор drift/heterogeneity rules;
4. dry-run instantiation на маленьком `CanonicalScenario`;
5. проверка, что результат можно сериализовать и сохранить;
6. diversity gate — новый шаблон не дублирует уже принятые шаблоны почти полностью.

### 3. Bounded retries

Если шаблон не прошел validation gates:

- попытаться не более `K` раз;
- `K` хранить в конфигурации;
- при исчерпании лимита фиксировать отказ и не блокировать весь pipeline.

### 4. Cache / reproducibility

Сохранять:

- `prompt_hash`;
- `model_config`;
- `accepted_template`;
- `validation_report`;
- `cache_key`.

Повторные запуски с тем же cache key должны по возможности использовать уже принятый шаблон без повторного live generation.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `hashlib`, `json`, `pathlib`
- `pytest`
- `unittest.mock` / `pytest-mock`

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_llm_template_output_is_parsed_and_validated`
2. `test_invalid_template_is_rejected`
3. `test_dry_run_instantiation_rejects_broken_template`
4. `test_cache_hit_skips_client_call`
5. `test_bounded_retry_stops_after_k_attempts`
6. `test_accepted_template_can_render_valid_l0`

Желательные тесты:

- test на diversity gate;
- snapshot test на cached accepted template.

## Done when / Acceptance criteria

Задача завершена, если:

- есть интерфейс LLM-assisted template generation;
- шаблоны проходят validation gates;
- принятые шаблоны кэшируются;
- unit tests полностью работают на mock/stub клиентах.

## Checklist

- [ ] Реализован интерфейс `TemplateGenerationClient` и LLM generator layer.
- [ ] Реализованы prompt builder, validator, dry-run instantiation и cache.
- [ ] Добавлены mock-based unit tests без live LLM calls.
- [ ] Запущены тесты (`pytest` или проектная команда тестов).
- [ ] Обновлен `README.md` с описанием LLM-assisted generator и cache policy.
- [ ] Обновлен `AGENTS.md`: структура LLM generator layer, правила тестирования без внешних сервисов, команды запуска.
- [ ] Проверено наличие docstrings и module docstrings.
- [ ] Обновлена структура репозитория в `AGENTS.md` и/или docs.

---

# TASK-04. Benchmark harness, адаптер к `ai-convertor`, `N` запусков и сбор stage-wise metrics

## Goal

Построить benchmark harness, который запускает `ai-convertor` на сгенерированных base/drift datasets, повторяет эксперимент `N` раз и сохраняет stage-wise и final metrics.

## Context

Это центральная задача для оценки качества `ai-convertor` на всех стадиях его работы, включая стабильность между независимыми прогонками.

## Scope

Нужно реализовать:

1. adapter/protocol к `ai-convertor`;
2. experiment config;
3. orchestrator для `N` запусков;
4. сохранение run artifacts;
5. stage-wise metrics collection;
6. финальную агрегацию run-level metrics.

Не нужно:

- строить красивые финальные отчеты;
- делать полноценный dashboard;
- вызывать live внешние сервисы в unit tests.

## Deliverables

- `src/synthetic_benchmark/benchmark/config.py`
- `src/synthetic_benchmark/benchmark/adapter.py`
- `src/synthetic_benchmark/benchmark/orchestrator.py`
- `src/synthetic_benchmark/metrics/models.py`
- `src/synthetic_benchmark/metrics/collectors.py`
- `src/synthetic_benchmark/storage/run_store.py`
- `tests/unit/synthetic_benchmark/benchmark/`
- `tests/fixtures/synthetic_benchmark/benchmark/`
- `docs/synthetic_benchmark/benchmark.md`
- пример benchmark config в `configs/synthetic_benchmark/benchmark/`

## Алгоритмика

### 1. Adapter к `ai-convertor`

Сделать протокол, который позволяет отделить benchmark-модуль от конкретной реализации конвертера.

Пример логических интерфейсов:

- `build_converter(training_bundle_set, run_config) -> BuildArtifact`
- `apply_converter(build_artifact, l0_json) -> ConversionResult`
- `collect_stage_artifacts(build_artifact) -> Optional[StageArtifacts]`

### 2. Экспериментальный контур

Для каждого benchmark run:

1. выбрать train/fit subset, если это нужно `ai-convertor`;
2. запустить сборку конвертера;
3. применить построенный конвертер к eval samples;
4. отдельно прогнать base set и drift set;
5. сохранить метрики и сырые артефакты;
6. повторить весь цикл `N` раз.

### 3. Stage-wise metrics

Если `ai-convertor` отдает промежуточные артефакты, собирать:

- source-structure recovery metrics;
- mapping quality metrics;
- build success / repair iterations;
- runtime validity.

Если промежуточные артефакты недоступны, benchmark все равно должен собирать end-to-end метрики.

### 4. Metric schema

Минимальные run-level поля:

- `run_id`
- `dataset_id`
- `split`
- `drift_class`
- `drift_severity`
- `build_success`
- `build_time_sec`
- `runtime_success_rate`
- `target_validation_rate`
- `semantic_score`
- `error_count`

### 5. Artifact store

Результаты одного run сохранять отдельно:

```text
artifacts/synthetic_benchmark/experiments/<exp_id>/runs/<run_id>/
├─ config.json
├─ build_artifact/
├─ metrics.json
├─ predictions/
└─ logs/
```

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `time`, `json`, `pathlib`
- `pytest`
- `pandas`/`pyarrow` — опционально, если уже есть в проекте

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_orchestrator_runs_n_independent_trials`
2. `test_failed_build_is_recorded_without_crashing_whole_experiment`
3. `test_metrics_are_saved_for_each_run`
4. `test_base_and_drift_sets_are_evaluated_separately`
5. `test_stage_artifacts_are_optional_but_supported`
6. `test_fake_adapter_enables_offline_tests`

Желательные тесты:

- snapshot test на run metrics;
- property test на aggregation invariants.

## Done when / Acceptance criteria

Задача завершена, если:

- benchmark harness умеет запускать `N` независимых прогонов;
- base и drift оцениваются раздельно;
- метрики сохраняются по каждому run;
- unit tests проходят полностью на fake/mock adapter.

## Checklist

- [ ] Реализован adapter/protocol для `ai-convertor`.
- [ ] Реализован orchestrator с параметром `N`.
- [ ] Реализованы collectors для stage-wise и end-to-end метрик.
- [ ] Добавлено сохранение run artifacts и metrics.
- [ ] Добавлены unit tests и offline fake adapter.
- [ ] Запущены тесты (`pytest` или проектная команда тестов).
- [ ] Обновлен `README.md` с описанием benchmark pipeline.
- [ ] Обновлен `AGENTS.md`: команды запуска benchmark, структура experiments/runs, test/lint команды.
- [ ] Проверено покрытие docstrings и module docstrings.
- [ ] Обновлена структура репозитория в `AGENTS.md` и/или docs.

---

# TASK-05. CLI, итоговые метрики, boxplots, отчеты и end-to-end smoke coverage

## Goal

Добавить поверх генераторов и benchmark harness удобный пользовательский слой:

- CLI/entry points;
- итоговую агрегацию метрик;
- boxplots и summary reports;
- end-to-end smoke сценарии;
- финальную документацию по модулю.

## Context

После этой задачи модуль должен быть пригоден для регулярного использования как исследовательский инструмент оценки `ai-convertor`.

## Scope

Нужно реализовать:

1. CLI-команды для генерации и benchmark;
2. агрегацию metrics across runs;
3. boxplot-ready summaries;
4. генерацию markdown/html/png отчетов;
5. end-to-end smoke tests на небольших конфигурациях;
6. финальное обновление docs, `README.md`, `AGENTS.md`.

Не нужно:

- строить веб-интерфейс;
- делать production scheduler;
- добавлять тяжелые внешние BI-инструменты.

## Deliverables

- `src/synthetic_benchmark/cli/main.py`
- `src/synthetic_benchmark/reports/aggregate.py`
- `src/synthetic_benchmark/reports/boxplots.py`
- `src/synthetic_benchmark/reports/summary.py`
- `tests/unit/synthetic_benchmark/reports/`
- `tests/integration/synthetic_benchmark/test_e2e_smoke.py`
- `docs/synthetic_benchmark/metrics.md`
- `docs/synthetic_benchmark/usage.md`
- пример конфигов в `configs/synthetic_benchmark/`

## Алгоритмика

### 1. CLI surface

Минимальный набор команд:

- `generate-deterministic`
- `generate-drift`
- `generate-llm-templates`
- `run-benchmark`
- `build-report`

### 2. Aggregation

По результатам `N` запусков считать:

- mean / median / std;
- min / max;
- quartiles / IQR;
- per-drift-class aggregates;
- per-stage aggregates.

### 3. Boxplots

Готовить boxplot-friendly таблицы минимум по:

- `semantic_score`;
- `target_validation_rate`;
- `build_time_sec`;
- `build_success` / success distribution;
- base vs drift comparison.

### 4. End-to-end smoke

Небольшой smoke pipeline должен уметь:

1. сгенерировать маленький deterministic dataset;
2. породить несколько drift examples;
3. прогнать fake adapter benchmark на `N=2..3`;
4. собрать summary report.

## Предпочтительный стек

- Python 3.11+
- `argparse` или `typer` (предпочесть стек проекта)
- `matplotlib` для boxplots
- `pytest`

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_cli_generate_deterministic_creates_expected_artifacts`
2. `test_cli_run_benchmark_creates_run_directories`
3. `test_report_aggregation_computes_boxplot_statistics`
4. `test_boxplot_export_creates_png`
5. `test_e2e_smoke_pipeline_finishes_successfully`

Желательные тесты:

- snapshot test на markdown summary;
- test на корректность grouped metrics.

## Done when / Acceptance criteria

Задача завершена, если:

- есть рабочий CLI;
- метрики агрегируются по `N` прогонам;
- boxplots и summary reports формируются автоматически;
- есть end-to-end smoke coverage.

## Checklist

- [ ] Реализованы CLI-команды для генерации, drift, benchmark и reports.
- [ ] Реализована агрегация итоговых метрик и boxplot-ready summaries.
- [ ] Реализован экспорт boxplots и summary reports.
- [ ] Добавлены unit tests и end-to-end smoke test.
- [ ] Запущены тесты (`pytest` или проектная команда тестов).
- [ ] Полностью обновлен `README.md` с quickstart по новому модулю.
- [ ] Полностью обновлен `AGENTS.md`: актуальная структура репозитория, команды генерации/benchmark/reporting, expected workflow для Codex.
- [ ] Проверено, что весь новый код задокументирован: docstrings и module docstrings.
- [ ] Обновлена структура репозитория в `AGENTS.md` и docs.

---

## Итог: что получится после реализации всех задач

После выполнения всех 5 задач в репозитории появится отдельный исследовательский модуль, который умеет:

1. детерминированно генерировать пары `JSON L0 / L1`;
2. расширять разнообразие `L0` через LLM-assisted template generation;
3. создавать heterogeneous subobjects;
4. генерировать drifted `L0`;
5. сохранять все датасеты и метаданные для воспроизводимости;
6. запускать `ai-convertor` `N` раз на base/drift наборах;
7. собирать stage-wise и final metrics;
8. строить summary reports и boxplots для оценки стабильности.

---

## Рекомендация по порядку реализации

1. Сначала зафиксировать канонические модели и deterministic core.
2. Затем добавить heterogeneity и drift.
3. Потом подключить LLM-assisted template generation через cache и validation gates.
4. После этого строить benchmark harness с `N` прогонами.
5. В конце добавить CLI, отчеты и end-to-end smoke coverage.
