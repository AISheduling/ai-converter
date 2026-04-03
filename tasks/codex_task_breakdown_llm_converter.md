# Разбиение эпика `offline-генерация конвертеров L0 -> L1` на задачи в формате Codex

## Что это за документ

Ниже — **5 автономных задач**, каждая из которых оформлена так, чтобы ее можно было отдавать в Codex как отдельную реализационную постановку.

Принципы разбиения:

- каждая задача имеет **четкий scope** и не требует live-вызовов LLM в тестах;
- каждая задача допускает **изолированную проверку unit tests**;
- у каждой задачи есть **алгоритмика**, **стек технологий**, **deliverables**, **acceptance criteria** и **чеклист**;
- задачи связаны зависимостями, но внутри каждой есть достаточно контекста для автономной реализации;
- формат ориентирован на репозиторий, в котором Codex должен не только писать код, но и **обновлять README, AGENTS.md, тесты и документацию**.

---

## Предлагаемая зависимость между задачами

- **TASK-01** — база репозитория, профилировщик `L0`, representative sampling, fingerprint.
- **TASK-02** — контракты `SourceSchemaSpec` и `TargetSchemaCard`, packing evidence.
- **TASK-03** — `MappingIR`, LLM-adapter слой, synthesis/aggregation/repair prompts.
- **TASK-04** — компилятор `MappingIR -> Python`, runtime-библиотека, acceptance suite.
- **TASK-05** — drift detection, patch adaptation, benchmark/evaluation harness.

Оптимальный порядок: `TASK-01 -> TASK-02 -> TASK-03 -> TASK-04 -> TASK-05`.

---

## Целевая структура репозитория

```text
repo/
├─ AGENTS.md
├─ README.md
├─ docs/
│  ├─ architecture/
│  ├─ prompts/
│  └─ evaluation/
├─ examples/
├─ prompts/
│  ├─ source_schema/
│  ├─ mapping_ir/
│  └─ repair/
├─ src/
│  └─ llm_converter/
│     ├─ profiling/
│     ├─ schema/
│     ├─ llm/
│     ├─ mapping_ir/
│     ├─ compiler/
│     ├─ validation/
│     ├─ drift/
│     └─ evaluation/
└─ tests/
   ├─ unit/
   ├─ integration/
   └─ fixtures/
```

Если текущий репозиторий уже организован иначе, Codex должен **адаптировать пути к существующей структуре**, но сохранить логическое разделение модулей.

---

## Общие требования для любой задачи

Эти требования повторяются в чеклисте каждой задачи и должны считаться обязательными:

1. Не использовать live network calls и live LLM calls в unit tests.
2. Предпочитать существующий стек репозитория и stdlib; новые зависимости добавлять только если без них решение заметно хуже.
3. Любой новый публичный класс или функция должны иметь type hints и docstrings.
4. В начале каждого нового Python-файла должен быть module docstring с кратким описанием назначения модуля.
5. Нужно обновлять `README.md` и `AGENTS.md`, если меняются команды запуска, структура каталогов, контракты или артефакты.
6. Проверки должны быть воспроизводимыми локально через `pytest` без внешних сервисов.
7. Если в репозитории уже есть стандартные команды (`make test`, `tox`, `poetry run pytest`, `uv run pytest`), использовать их; если нет — базовый путь проверки указывать через `pytest`.

---

# TASK-01. Каркас репозитория, детерминированный профилировщик `L0`, representative sampling и fingerprint

## Цель

Построить фундаментальный модуль, который принимает новый `L0`-вход (`CSV`, `JSON`, опционально `JSONL`) и детерминированно строит:

- машиночитаемый профиль формата;
- статистики по полям и путям;
- representative samples;
- стабильный fingerprint схемы.

Это база для всех следующих задач. После завершения этой задачи последующие модули должны получать на вход **не сырой файл**, а нормализованный profile report.

## Покрываемые части эпика

- Этап 0 из эпика: профилировщик `L0`.
- WP-1: `profile_builder`, `sample_selector`, `schema_fingerprint`.

## Scope

В рамках задачи нужно реализовать:

1. Нормализованный загрузчик `CSV/JSON/JSONL`.
2. Профилировщик путей/полей.
3. Выбор representative samples.
4. Fingerprint схемы.
5. Формат report-артефакта.
6. Unit tests и пример отчета.

В рамках этой задачи **не нужно**:

- вызывать LLM;
- восстанавливать семантические имена полей;
- строить `SourceSchemaSpec`;
- компилировать конвертер.

## Deliverables

Минимальный набор артефактов:

- `src/llm_converter/profiling/models.py`
- `src/llm_converter/profiling/loaders.py`
- `src/llm_converter/profiling/csv_profiler.py`
- `src/llm_converter/profiling/json_profiler.py`
- `src/llm_converter/profiling/sampling.py`
- `src/llm_converter/profiling/fingerprint.py`
- `src/llm_converter/profiling/report_builder.py`
- `tests/unit/profiling/`
- `tests/fixtures/profiling/`
- `docs/architecture/profiling.md`

## Алгоритмика

### 1. Нормализация входа

- Для `CSV`:
  - детектировать delimiter через `csv.Sniffer` или эквивалент;
  - читать данные в табличную форму;
  - нормализовать столбцы в список row-объектов;
  - сохранить исходное имя столбца и нормализованное имя для внутренних вычислений.
- Для `JSON/JSONL`:
  - поддержать top-level `dict`, `list[dict]`, nested objects;
  - развернуть структуру в path-based представление (`a.b.c`, `items[].id`);
  - фиксировать глубину вложенности и кардинальность массивов.

### 2. Построение field/path profile

Для каждого поля или path собирать:

- `path`;
- `observed_types` и их частоты;
- `null_ratio`;
- `present_ratio`;
- `unique_ratio`;
- `min/max` для чисел;
- `length stats` для строк/массивов;
- top values для enum-кандидатов;
- sample values;
- candidate id flag, если `unique_ratio` близок к 1.0.

### 3. Representative sampling

Реализовать greedy-алгоритм выбора примеров, который максимизирует:

- покрытие разных полей;
- покрытие редких типов и значений;
- полноту строки/объекта;
- разнообразие вложенных структур.

Практически:

- на каждой итерации выбирать запись с максимальным score;
- `score = new_path_coverage + completeness_bonus + rarity_bonus`;
- tie-break должен быть детерминированным, например по исходному индексу.

### 4. Fingerprint

Fingerprint должен быть **устойчивым к перестановке строк** и отражать структуру, а не конкретный порядок данных.

Рекомендуемый подход:

- канонизировать profile report;
- отсортировать paths;
- сериализовать ключевые атрибуты (`path`, dominant type, nullability, cardinality);
- вычислить hash.

### 5. Report builder

Собрать единый `ProfileReport`, пригодный для:

- дальнейшей упаковки в prompt evidence;
- drift detection;
- snapshot tests.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2 для моделей профиля
- `pandas` для надежного чтения `CSV` (если уже есть в проекте; иначе можно ограничиться stdlib + небольшим адаптером)
- stdlib `json`, `csv`, `hashlib`, `statistics`
- `pytest`
- `hypothesis` для property-based tests fingerprint/sampling

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_csv_profile_detects_columns_and_types`
2. `test_json_profile_flattens_nested_paths`
3. `test_profile_is_stable_under_row_reordering`
4. `test_sampling_is_deterministic`
5. `test_sampling_prefers_records_with_new_coverage`
6. `test_fingerprint_changes_on_structural_change`
7. `test_fingerprint_does_not_change_on_value_order_change`

Дополнительно желательны:

- snapshot test на итоговый `ProfileReport`;
- property test, что fingerprint одинаков для перестановок одной и той же выборки.

## Acceptance criteria

Задача считается завершенной, если:

- для `CSV` и `JSON` можно получить единый `ProfileReport`;
- отчет устойчив к перестановке входных записей;
- sampling детерминирован и покрывает редкие структуры лучше случайной выборки;
- fingerprint меняется при структурном изменении формата и не меняется при простой перестановке строк;
- весь код покрыт unit tests без вызова внешних сервисов.

## Чеклист

- [ ] Реализованы профилировщик, sampling и fingerprint в пределах заявленного scope
- [ ] Добавлены unit tests в `tests/unit/profiling/`
- [ ] Выполнен запуск релевантных тестов (`pytest tests/unit/profiling -q` или эквивалент команды репозитория)
- [ ] Обновлен `README.md` с разделом про profiling/report artifacts
- [ ] Обновлен `AGENTS.md`: структура `src/llm_converter/profiling`, команды тестирования, расположение fixtures/reports
- [ ] Во всех новых/измененных файлах есть module docstring
- [ ] У всех публичных функций и классов есть docstrings и type hints
- [ ] Если добавлены зависимости, обновлены `pyproject.toml`/`requirements*` и README/AGENTS
- [ ] В финальном отчете Codex перечислил измененные файлы, запущенные команды и остаточные риски

---

# TASK-02. Контракты `SourceSchemaSpec` и `TargetSchemaCard`, evidence packing

## Цель

Построить слой формальных контрактов между profiling-частью и будущими LLM-шагами:

- модели `SourceSchemaSpec`;
- модели `TargetSchemaCard`;
- экспорт `Pydantic L1 -> TargetSchemaCard`;
- budgeted evidence packing для передачи профиля в LLM.

После завершения этой задачи у проекта должен появиться стабильный **schema-first слой**, который не зависит от конкретной модели LLM.

## Покрываемые части эпика

- WP-2: контракт `SourceSchemaSpec`.
- WP-3: генерация `TargetSchemaCard`.
- Алгоритмические решения: `budgeted evidence packing`, `schema-first contracts`.

## Scope

В рамках задачи нужно реализовать:

1. Pydantic-модели `SourceSchemaSpec`.
2. Pydantic-модели `TargetSchemaCard`.
3. Экспортер из `L1`-моделей в `TargetSchemaCard`.
4. Evidence packer, который превращает `ProfileReport` в компактный пакет фактов для LLM.
5. Агрегатор кандидатов `SourceSchemaSpec` как детерминированную post-processing стадию.

В рамках этой задачи **не нужно**:

- подключать реальный LLM-клиент;
- синтезировать `MappingIR`;
- компилировать Python-конвертер.

## Deliverables

- `src/llm_converter/schema/source_spec_models.py`
- `src/llm_converter/schema/source_spec_normalizer.py`
- `src/llm_converter/schema/source_spec_aggregator.py`
- `src/llm_converter/schema/target_card_models.py`
- `src/llm_converter/schema/target_card_builder.py`
- `src/llm_converter/schema/evidence_packer.py`
- `tests/unit/schema/`
- `tests/fixtures/schema/`
- `docs/architecture/schema_contracts.md`

## Алгоритмика

### 1. `SourceSchemaSpec`

Спроектировать каноническую структуру источника как набор сущностей и полей. Для каждого поля желательно хранить:

- `path`;
- `semantic_name`;
- `description`;
- `dtype`;
- `cardinality`;
- `nullable`;
- `aliases`;
- `unit`;
- `examples`;
- `confidence`.

Важно: `SourceSchemaSpec` должен быть **структурой для последующей агрегации**, а не только финальным красивым JSON.

### 2. `TargetSchemaCard`

Экспортер из `Pydantic` должен:

- рекурсивно обходить вложенные модели;
- извлекать типы полей, обязательность, defaults, enum values;
- поднимать в card описания из `Field(description=...)` и `json_schema_extra`, если они есть;
- строить компактное представление, пригодное для prompt packing.

### 3. Budgeted evidence packing

Нужно реализовать упаковщик evidence, который не отправляет LLM весь raw report целиком, а выбирает:

- наиболее информативные paths;
- representative samples;
- summary statistics;
- optional `format_hint`.

Упаковщик должен иметь budget в условных токенах/символах и детерминированно отбрасывать менее ценные элементы.

Рекомендуемая эвристика при packing:

- сохранять paths с высокой уникальностью и высокой частотой;
- отдельно сохранять редкие, но структурно важные paths;
- включать 5–20 representative samples, но только если они добавляют новую информацию;
- поддерживать режимы `compact`, `balanced`, `full`.

### 4. Aggregation кандидатов

Так как в будущих задачах `SourceSchemaSpec` будет приходить в нескольких вариантах от LLM, уже сейчас нужен детерминированный агрегатор, который умеет:

- нормализовать названия полей;
- объединять алиасы;
- сливать одинаковые fields из нескольких кандидатов;
- считать итоговый confidence через vote/weighting;
- отбрасывать очевидно противоречивые поля.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `typing`, `inspect`, `dataclasses`, `collections`
- `pytest`
- `hypothesis` для property tests normalizer/aggregator

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_target_card_builder_exports_nested_pydantic_models`
2. `test_target_card_builder_preserves_required_optional_flags`
3. `test_target_card_builder_extracts_descriptions_and_enums`
4. `test_evidence_packer_respects_budget`
5. `test_evidence_packer_keeps_high_value_paths`
6. `test_source_spec_aggregator_merges_aliases_and_confidence`
7. `test_source_spec_normalizer_is_deterministic`

Дополнительно желательны:

- snapshot tests на `TargetSchemaCard`;
- property test, что aggregation не зависит от перестановки входных кандидатов.

## Acceptance criteria

Задача считается завершенной, если:

- `SourceSchemaSpec` и `TargetSchemaCard` формально описаны `Pydantic`-моделями;
- для любой `L1`-модели можно получить `TargetSchemaCard`;
- evidence packer детерминированно сжимает profile report в ограниченный пакет фактов;
- агрегатор кандидатов способен объединять как минимум rename/alias совпадения и выставлять confidence;
- unit tests проходят без LLM и без сети.

## Чеклист

- [ ] Реализованы `SourceSchemaSpec`, `TargetSchemaCard`, evidence packing и aggregation в пределах scope
- [ ] Добавлены unit tests в `tests/unit/schema/`
- [ ] Выполнен запуск релевантных тестов (`pytest tests/unit/schema -q` или эквивалент)
- [ ] Обновлен `README.md` с разделом про schema contracts и export из `Pydantic`
- [ ] Обновлен `AGENTS.md`: структура `src/llm_converter/schema`, команды тестирования, расположение schema fixtures
- [ ] Во всех новых/измененных файлах есть module docstring
- [ ] У всех публичных функций и классов есть docstrings и type hints
- [ ] Если добавлены зависимости, обновлены `pyproject.toml`/`requirements*` и README/AGENTS
- [ ] В финальном отчете Codex перечислил измененные файлы, запущенные команды и остаточные риски

---

# TASK-03. `MappingIR`, LLM-adapter слой, synthesis/aggregation/repair prompts

## Цель

Реализовать промежуточный DSL/IR преобразований и изолированный слой работы с LLM, который позволяет:

- синтезировать `SourceSchemaSpec` из evidence;
- синтезировать `MappingIR` из `SourceSchemaSpec + TargetSchemaCard`;
- агрегировать несколько кандидатов;
- готовить bounded repair prompts.

Важно: задача должна быть реализована так, чтобы unit tests использовали **fake LLM client** и не зависели от внешней модели.

## Покрываемые части эпика

- WP-4: дизайн `MappingIR`.
- WP-5: LLM-синтез `MappingIR`.
- Алгоритмические решения: `ensemble prompting + aggregation`, `bounded repair`.

## Scope

В рамках задачи нужно реализовать:

1. Pydantic-модели `MappingIR`.
2. Валидатор `MappingIR`.
3. Интерфейс `LLMAdapter`.
4. Prompt renderers для source schema synthesis, mapping synthesis и repair.
5. Оркестратор многокандидатной генерации и ранжирования.
6. Fake adapter для unit tests.

В рамках этой задачи **не нужно**:

- вызывать реальную модель;
- компилировать `MappingIR` в Python;
- прогонять end-to-end benchmark.

## Deliverables

- `src/llm_converter/llm/protocol.py`
- `src/llm_converter/llm/fake_client.py`
- `src/llm_converter/llm/prompt_renderers.py`
- `src/llm_converter/mapping_ir/models.py`
- `src/llm_converter/mapping_ir/validator.py`
- `src/llm_converter/mapping_ir/synthesizer.py`
- `src/llm_converter/mapping_ir/ranker.py`
- `src/llm_converter/mapping_ir/repair.py`
- `prompts/source_schema/`
- `prompts/mapping_ir/`
- `prompts/repair/`
- `tests/unit/mapping_ir/`
- `docs/prompts/mapping_ir.md`

## Алгоритмика

### 1. Дизайн `MappingIR`

`MappingIR` должен быть ограниченным, типизированным и валидируемым. Минимальный набор операций:

- `copy`
- `rename`
- `cast`
- `map_enum`
- `unit_convert`
- `split`
- `merge`
- `nest`
- `unnest`
- `derive`
- `default`
- `drop`
- `validate`

Структура IR должна содержать:

- список source refs;
- список transformation steps;
- target assignments;
- optional preconditions/postconditions.

### 2. Валидация `MappingIR`

Нужно проверять:

- существование всех source refs;
- корректность target paths;
- отсутствие конфликтующих записей в один target, если это явно не разрешено;
- допустимость типов аргументов для операции;
- ацикличность зависимостей между steps.

### 3. `LLMAdapter`

Определить интерфейс, за который будут прятаться конкретные модели и API. Минимальный контракт:

- `generate_text(...)`
- `generate_structured(...)`
- возможность принять prompt, schema/model class и metadata;
- единый формат ответа с raw text, parsed object, usage/meta, errors.

### 4. Prompt renderers

Нужно сделать шаблонизатор для трех сценариев:

- synthesis `ProfileReport -> SourceSchemaSpec`
- synthesis `SourceSchemaSpec + TargetSchemaCard -> MappingIR`
- repair prompt на основе failing case

Шаблоны должны быть раздельными, храниться как файлы и поддерживать versioning.

### 5. Многокандидатная генерация и агрегация

Оркестратор должен поддерживать режим `N candidates`:

- сгенерировать несколько structured outputs;
- распарсить их;
- прогнать validator;
- оценить coverage target fields;
- ранжировать кандидатов;
- вернуть лучший кандидат или ensemble aggregate.

### 6. Repair prompt builder

В repair prompt должны входить:

- failing fixture;
- log ошибки;
- diff между expected и actual;
- проблемные rules;
- ограничение на локальный patch, а не полную регенерацию.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `json`, `pathlib`, `abc`, `typing`, `difflib`
- `pytest`
- `hypothesis` для validator invariants

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_mapping_ir_validator_rejects_unknown_source_refs`
2. `test_mapping_ir_validator_rejects_conflicting_target_writes`
3. `test_mapping_ir_validator_accepts_valid_program`
4. `test_prompt_renderer_includes_required_sections`
5. `test_synthesizer_ranks_candidates_by_validity_and_coverage`
6. `test_fake_llm_adapter_supports_structured_outputs`
7. `test_repair_prompt_contains_failure_context`
8. `test_candidate_aggregation_is_order_invariant`

Дополнительно желательны:

- snapshot tests на prompts;
- property tests на validator (например, что программа с циклом всегда отклоняется).

## Acceptance criteria

Задача считается завершенной, если:

- `MappingIR` описан как формальная модель и валидируется автоматически;
- есть изолированный `LLMAdapter`, который можно заменить реальным клиентом позднее;
- prompt renderers и candidate orchestration работают поверх fake adapter;
- candidate ranking учитывает structural validity и coverage;
- repair prompt builder формирует локальный контекст для patch-based исправления;
- все unit tests работают без внешней модели и без сети.

## Чеклист

- [ ] Реализованы `MappingIR`, validator, LLM-adapter и prompt/render/synthesis слой в пределах scope
- [ ] Добавлены unit tests в `tests/unit/mapping_ir/`
- [ ] Выполнен запуск релевантных тестов (`pytest tests/unit/mapping_ir -q` или эквивалент)
- [ ] Обновлен `README.md` с разделом про `MappingIR`, prompts и fake adapter
- [ ] Обновлен `AGENTS.md`: структура `src/llm_converter/mapping_ir` и `src/llm_converter/llm`, команды тестирования, расположение prompt templates
- [ ] Во всех новых/измененных файлах есть module docstring
- [ ] У всех публичных функций и классов есть docstrings и type hints
- [ ] Если добавлены зависимости, обновлены `pyproject.toml`/`requirements*` и README/AGENTS
- [ ] В финальном отчете Codex перечислил измененные файлы, запущенные команды и остаточные риски

---

# TASK-04. Компилятор `MappingIR -> Python`, runtime operations и acceptance suite

## Цель

Собрать детерминированный runtime-контур: из валидного `MappingIR` должен рождаться исполняемый Python-конвертер, который не использует LLM при выполнении и может быть принят через многоуровневую валидацию.

## Покрываемые части эпика

- WP-6: компилятор `MappingIR -> Python`.
- WP-7: acceptance suite.
- Этапы эпика: compile -> validate -> bounded repair loop.

## Scope

В рамках задачи нужно реализовать:

1. Компилятор `MappingIR -> Python module`.
2. Библиотеку runtime-операций.
3. Structural validation через `Pydantic L1`.
4. Semantic assertions и property tests.
5. Acceptance orchestrator.
6. Bounded repair loop orchestration без live LLM в unit tests.

В рамках этой задачи **не нужно**:

- реализовывать drift detection;
- строить финальный benchmark по baseline.

## Deliverables

- `src/llm_converter/compiler/compiler.py`
- `src/llm_converter/compiler/module_loader.py`
- `src/llm_converter/compiler/runtime_ops.py`
- `src/llm_converter/validation/structural.py`
- `src/llm_converter/validation/semantic.py`
- `src/llm_converter/validation/acceptance.py`
- `src/llm_converter/validation/repair_loop.py`
- `tests/unit/compiler/`
- `tests/unit/validation/`
- `tests/integration/converter_pipeline/`
- `docs/architecture/compiler_and_validation.md`

## Алгоритмика

### 1. Компиляция `MappingIR`

Нужно преобразовать валидный `MappingIR` в Python-модуль с функцией вида `convert(record) -> L1-compatible dict`.

Рекомендуемый pipeline:

1. Нормализовать IR.
2. Топологически отсортировать transformation steps.
3. Для каждой операции сгенерировать вызов pure runtime helper.
4. Сгенерировать module source code.
5. Импортировать модуль через безопасный loader.

Важно: generated module должен быть детерминированным и воспроизводимым.

### 2. Runtime operations

Нужны чистые функции для:

- `cast`
- `map_enum`
- `unit_convert`
- `split`
- `merge`
- `nest/unnest`
- `default`
- `derive`

Для `derive` нельзя использовать свободный `eval`. Нужен ограниченный механизм:

- либо whitelist допустимых выражений;
- либо небольшой AST-evaluator над безопасным подмножеством Python.

### 3. Structural validation

После выполнения конвертера результат должен валидироваться через `Pydantic L1` и давать понятный отчет:

- отсутствующие обязательные поля;
- type mismatch;
- enum violations;
- nested path violations.

### 4. Semantic assertions

Нужен слой semantic checks поверх structural validity. Минимум:

- field equality для обязательных маппингов;
- корректность unit conversion;
- корректность enum mapping;
- корректность derived fields.

### 5. Acceptance orchestrator

Оркестратор должен принимать:

- compiled converter;
- fixture dataset;
- target model;
- semantic assertions;
- лимит repair iterations.

И возвращать единый `AcceptanceReport` со статусами:

- `structural_validity`
- `execution_success`
- `semantic_validity`
- `coverage`
- `repair_iterations`

### 6. Bounded repair loop

Даже без live LLM в unit tests нужно реализовать orchestration-контур:

- если validation failed, собрать failure bundle;
- вызвать repair strategy interface;
- применить patch;
- перекомпилировать;
- остановиться не позже `max_repair_iterations`.

В unit tests repair strategy должна быть fake/stub.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `ast`, `importlib`, `tempfile`, `pathlib`
- `pytest`
- `hypothesis` для property tests runtime ops

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_compiler_emits_importable_module`
2. `test_compiled_converter_executes_without_llm`
3. `test_runtime_cast_and_enum_mapping`
4. `test_runtime_unit_convert`
5. `test_safe_derive_rejects_disallowed_expressions`
6. `test_structural_validation_reports_missing_required_fields`
7. `test_semantic_assertions_detect_wrong_mapping`
8. `test_acceptance_orchestrator_builds_report`
9. `test_bounded_repair_loop_stops_at_limit`
10. `test_bounded_repair_loop_succeeds_with_fake_patch_strategy`

Дополнительно желательны:

- integration smoke test на `ProfileReport -> SourceSchemaSpec stub -> MappingIR fixture -> compiled converter -> validation`;
- property tests для runtime helpers.

## Acceptance criteria

Задача считается завершенной, если:

- из валидного `MappingIR` строится исполняемый Python-модуль;
- compiled converter работает без LLM;
- есть структурная и семантическая проверка результата;
- acceptance suite выдает единый отчет и поддерживает bounded repair orchestration;
- unit tests и smoke integration tests проходят локально без внешних сервисов.

## Чеклист

- [ ] Реализованы compiler/runtime/validation/repair orchestration в пределах scope
- [ ] Добавлены unit tests в `tests/unit/compiler/` и `tests/unit/validation/`
- [ ] Добавлены smoke integration tests в `tests/integration/converter_pipeline/`
- [ ] Выполнен запуск релевантных тестов (`pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q` или эквивалент)
- [ ] Обновлен `README.md` с разделом про compile/runtime/acceptance workflow
- [ ] Обновлен `AGENTS.md`: структура `src/llm_converter/compiler` и `src/llm_converter/validation`, команды тестирования, расположение integration fixtures
- [ ] Во всех новых/измененных файлах есть module docstring
- [ ] У всех публичных функций и классов есть docstrings и type hints
- [ ] Если добавлены зависимости, обновлены `pyproject.toml`/`requirements*` и README/AGENTS
- [ ] В финальном отчете Codex перечислил измененные файлы, запущенные команды и остаточные риски

---

# TASK-05. Drift detection, patch adaptation и benchmark/evaluation harness

## Цель

Завершить offline-пайплайн двумя последними слоями:

- детектировать изменения входного формата относительно эталона;
- локально адаптировать конвертер через patch, а не полную регенерацию;
- измерять качество системы на воспроизводимом benchmark/evaluation harness.

## Покрываемые части эпика

- WP-8: drift detection и patch-generation.
- WP-9: экспериментальный контур и baseline comparison.

## Scope

В рамках задачи нужно реализовать:

1. Drift classifier на основе profile/fingerprint diff.
2. Patch-модели и patch apply.
3. Deterministic heuristics для compatible drift.
4. Evaluation/benchmark harness.
5. Метрики и отчеты.

В рамках этой задачи **не нужно**:

- строить полноценный production scheduler для длительных экспериментов;
- подключать live external datasets;
- требовать live LLM в unit tests.

## Deliverables

- `src/llm_converter/drift/models.py`
- `src/llm_converter/drift/classifier.py`
- `src/llm_converter/drift/heuristics.py`
- `src/llm_converter/drift/patch_apply.py`
- `src/llm_converter/evaluation/metrics.py`
- `src/llm_converter/evaluation/benchmark.py`
- `src/llm_converter/evaluation/reporting.py`
- `tests/unit/drift/`
- `tests/unit/evaluation/`
- `tests/fixtures/drift/`
- `docs/evaluation/benchmark_protocol.md`
- `examples/benchmark_config.*`

## Алгоритмика

### 1. Drift classification

Сравнение нового профиля с baseline должно использовать:

- различия в paths/columns;
- различия доминирующих типов;
- nullable/present ratio;
- cardinality changes;
- enum changes;
- unit changes.

Минимальные классы drift:

- `additive_compatible`
- `rename_compatible`
- `semantic_change`
- `breaking_change`

### 2. Deterministic heuristics

До обращения к LLM нужно уметь решать часть drift-случаев детерминированно:

- alias addition;
- rename by similarity + same type;
- safe cast insertion;
- optional field addition;
- simple enum extension.

### 3. Patch model

Patch должен быть локальным и версионируемым. Минимально поддержать:

- patch для `SourceSchemaSpec`;
- patch для `MappingIR`;
- audit trail: что изменилось и почему.

### 4. Benchmark harness

Нужен единый интерфейс, который умеет запускать:

- baseline converters;
- compiled converter pipeline;
- drift scenarios;
- repair scenarios.

Метрики минимум:

- required field accuracy;
- macro/micro field accuracy;
- pass@1 на готовый конвертер;
- число repair iterations;
- доля compatible drift, закрытого patch-ом;
- preparation cost;
- runtime conversion cost.

### 5. Reporting

Результаты нужно собирать в единый отчет:

- machine-readable `json/csv`;
- human-readable markdown summary;
- сравнение по сценариям и baseline.

## Предпочтительный стек

- Python 3.11+
- `pydantic` v2
- stdlib `difflib`, `statistics`, `time`, `json`
- `pytest`
- `hypothesis` для property tests diff/patch invariants

## Изолированная проверка unit tests

Обязательные тесты:

1. `test_drift_classifier_detects_additive_change`
2. `test_drift_classifier_detects_rename_change`
3. `test_drift_classifier_detects_breaking_change`
4. `test_patch_apply_updates_mapping_ir_locally`
5. `test_heuristics_resolve_safe_rename_without_llm`
6. `test_metrics_compute_required_field_accuracy`
7. `test_metrics_compute_macro_micro_accuracy`
8. `test_benchmark_harness_runs_on_fake_converters`
9. `test_reporting_exports_machine_readable_and_md_outputs`

Дополнительно желательны:

- property test, что локальный compatible patch не меняет не затронутые sections;
- fixture-based test на пару synthetic drift scenarios.

## Acceptance criteria

Задача считается завершенной, если:

- drift detection различает совместимые и разрушающие изменения;
- для compatible drift можно выпустить локальный patch без полной регенерации;
- benchmark harness воспроизводимо считает ключевые метрики;
- есть экспорт отчетов и baseline comparison;
- unit tests работают локально без сети.

## Чеклист

- [ ] Реализованы drift classification, patch apply и evaluation harness в пределах scope
- [ ] Добавлены unit tests в `tests/unit/drift/` и `tests/unit/evaluation/`
- [ ] Выполнен запуск релевантных тестов (`pytest tests/unit/drift tests/unit/evaluation -q` или эквивалент)
- [ ] Обновлен `README.md` с разделом про drift handling и benchmark protocol
- [ ] Обновлен `AGENTS.md`: структура `src/llm_converter/drift` и `src/llm_converter/evaluation`, команды тестирования, расположение benchmark fixtures/configs
- [ ] Во всех новых/измененных файлах есть module docstring
- [ ] У всех публичных функций и классов есть docstrings и type hints
- [ ] Если добавлены зависимости, обновлены `pyproject.toml`/`requirements*` и README/AGENTS
- [ ] В финальном отчете Codex перечислил измененные файлы, запущенные команды и остаточные риски

---

## Единый шаблон для запуска задачи в Codex

Этот кусок можно использовать как обертку для любой из задач выше:

```text
Реализуй задачу ниже в текущем репозитории. Сначала изучи существующую структуру проекта и подстрой пути и команды под нее, но сохрани логическое разделение модулей, описанное в задаче. Работай строго в пределах scope задачи. Не используй live network calls и live LLM calls в тестах. Предпочитай текущий стек репозитория и stdlib; новые зависимости добавляй только если они действительно нужны, и тогда обнови pyproject/requirements, README и AGENTS.md.

Обязательно:
1. написать/обновить unit tests;
2. прогнать релевантные тесты;
3. обновить README.md;
4. обновить AGENTS.md (структура репозитория, команды, новые артефакты и ограничения);
5. убедиться, что во всех новых/измененных файлах есть module docstring, а у публичных сущностей есть docstrings и type hints;
6. в финальном ответе перечислить измененные файлы, выполненные команды, результаты тестов и оставшиеся риски.

Ниже постановка задачи:
<вставить текст одной задачи из этого документа>
```

---

## Что можно делать параллельно

После завершения `TASK-01` допустим такой параллелизм:

- `TASK-02` можно вести независимо от компилятора;
- `TASK-03` можно вести поверх contract layer из `TASK-02`;
- часть тестовых fixtures для `TASK-04` можно готовить заранее;
- `TASK-05` логично начинать после появления хотя бы одного рабочего compiled converter, но метрики и reporting можно вынести в отдельную ветку раньше.

---

## Минимальная последовательность merge

1. Merge `TASK-01`.
2. Merge `TASK-02`.
3. Merge `TASK-03`.
4. Merge `TASK-04`.
5. Merge `TASK-05`.

Это даст стабильную эволюцию репозитория: сначала deterministic data layer, потом schema contracts, потом synthesis layer, потом execution layer, потом adaptation/evaluation.
