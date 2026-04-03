# Крупная задача: offline-генерация конвертеров `L0 -> L1` на основе LLM с детерминированным runtime

## 1. Постановка задачи

Нужно разработать воспроизводимый pipeline, который **один раз на новый тип входного формата `L0`** использует LLM для анализа структуры, синтеза правил преобразования и генерации конвертера в канонический слой `L1`, после чего **все последующие конвертации выполняются без LLM** обычным детерминированным кодом.

Под `L0` понимается внешний формат проекта в `CSV`, `JSON` или близком таблично-иерархическом представлении. Под `L1` понимается уже заданная целевая модель на `Pydantic`. Допускается использование промпт-подсказок:

- для описания структуры `L0`;
- для генерации соответствий `L0 -> L1`;
- для адаптации к дрейфу формата.

Ключевое ограничение: **число вызовов LLM должно быть конечным на один новый формат и не зависеть от числа последующих конвертаций**. Это соответствует более надежной стратегии `CODEGEN/compile-once`, а не `DIRECT`-преобразованию каждого объекта через LLM [@falcao2025interop; @steiner2026e2edi].

---

## 2. Почему это отдельная крупная задача

Современные работы по schema mapping и end-to-end data integration показывают, что LLM уже можно использовать не только для разовой экстракции, но и для **конфигурирования артефактов интеграции**: schema mappings, normalization rules, training data и validation artifacts [@buss2025scalable; @steiner2026e2edi]. Одновременно свежие бенчмарки структурированной генерации показывают, что полагаться только на формально валидный JSON недостаточно: при росте ширины и глубины схем семантическая надежность резко падает [@geng2025jsonschemabench; @ferguson2026extractbench; @reddy2026dccd].

Из этого следует, что задача должна решаться не как “один prompt -> один JSON”, а как **полноценный synthesis pipeline**:

1. детерминированное профилирование формата;
2. schema induction с LLM;
3. генерация промежуточного IR/DSL преобразования;
4. компиляция в Python-конвертер;
5. многоуровневая валидация;
6. patch-based адаптация при дрейфе формата.

Такой дизайн согласуется и с практикой schema-first систем, и с работами по LLM-ориентированным DSL, где ограниченный и канонический промежуточный язык дает более надежную генерацию, чем немедленная генерация произвольного Python-кода [@shrimal2025parse; @almazrouei2025anka; @sigdel2026schemafirst].

---

## 3. Цель

Создать архитектуру и реализацию offline-контура, который для каждого нового семейства входных форматов `L0`:

- автоматически или полуавтоматически восстанавливает структуру формата;
- строит семантическое соответствие между `L0` и `L1`;
- синтезирует детерминированный конвертер `L0 -> L1`;
- валидирует корректность на размеченных и property-based тестах;
- детектирует изменения формата `L0` и локально расширяет конвертер;
- не требует вызовов LLM на этапе массовой эксплуатации.

---

## 4. Научная гипотеза

Если строить конвертеры не напрямую через runtime prompting, а через схему

`profile -> source schema spec -> mapping IR -> compiled converter -> validation -> patch adaptation`,

то можно получить систему, которая:

- надежнее прямой LLM-конверсии на каждом объекте;
- лучше переносит неочевидные преобразования, включая переименования, вложенность, enum mapping и unit conversion;
- дает воспроизводимый и проверяемый артефакт на стороне исполнения;
- лучше адаптируется к дрейфу входного формата за счет локальных патчей, а не полной регенерации [@falcao2025interop; @neubauer2025jsonschema; @duanis2025jsonwhisperer].

---

## 5. Объект разработки

### 5.1. Входы

- `L0`-форматы: `CSV`, `JSON`, при необходимости `JSONL` и близкие табличные/иерархические варианты;
- небольшой набор representative samples для нового формата;
- опциональная текстовая подсказка о домене и смысле полей;
- заранее заданные `Pydantic`-модели слоя `L1`.

### 5.2. Выходы

Для каждого нового формата система должна порождать набор артефактов:

1. `SourceSchemaSpec` — каноническое описание `L0`.
2. `TargetSchemaCard` — LLM-оптимизированное описание `L1` поверх существующих `Pydantic`-моделей.
3. `MappingIR` — промежуточное формальное описание преобразования `L0 -> L1`.
4. `ConverterPackage` — скомпилированный Python-конвертер, тесты, валидаторы.
5. `DriftReport` — отчет о дрейфе нового экземпляра `L0` относительно эталона.
6. `Patch` — локальное расширение `SourceSchemaSpec`/`MappingIR`, если формат изменился.

---

## 6. Границы задачи

### Входит в задачу

- автоматическое и полуавтоматическое восстановление схемы входного формата;
- генерация соответствий между `L0` и `L1`;
- генерация и компиляция конвертера;
- синтаксическая, структурная и семантическая валидация;
- обнаружение и обработка дрейфа формата;
- экспериментальное сравнение с базовыми подходами.

### Не входит в задачу

- runtime-конвертация каждого нового объекта через LLM;
- бесконечная онлайн-адаптация без контроля версий;
- покрытие произвольных мультимодальных документов без отдельного OCR/document AI контура;
- построение общего data lake/MDM-решения вне задачи `L0 -> L1`.

---

## 7. Основные требования

### 7.1. Функциональные требования

**FR-1.** Система должна поддерживать как минимум `CSV` и `JSON`-входы.

**FR-2.** Для каждого нового формата `L0` число LLM-вызовов должно быть ограничено фиксированным бюджетом `K = K_profile_hint + K_schema + K_mapping + K_repair`.

**FR-3.** После публикации `ConverterPackage` конвертация новых экземпляров должна выполняться без LLM.

**FR-4.** Система должна уметь использовать опциональные подсказки о формате и подсказки о правилах конвертации.

**FR-5.** Система должна генерировать промежуточный `MappingIR`, а не только финальный Python-код.

**FR-6.** Система должна компилировать `MappingIR` в исполняемый Python-модуль.

**FR-7.** Система должна валидировать результат минимум на трех уровнях:

- соответствие `Pydantic`/JSON Schema;
- исполнимость конвертера;
- семантическая корректность результата.

**FR-8.** Система должна детектировать дрейф входного формата относительно эталонного профиля.

**FR-9.** Для совместимого дрейфа система должна уметь выпускать patch вместо полной регенерации конвертера.

### 7.2. Нефункциональные требования

**NFR-1. Качество.** Приоритет — корректность и воспроизводимость, а не минимальная стоимость генерации.

**NFR-2. Детерминизм исполнения.** Runtime-конвертация должна быть полностью детерминированной.

**NFR-3. Наблюдаемость.** Должны сохраняться профили, prompt inputs, ответы модели, тестовые трассы и результаты repair-итераций.

**NFR-4. Версионирование.** Все артефакты `SourceSchemaSpec`, `MappingIR`, `ConverterPackage` и `Patch` должны версионироваться.

**NFR-5. Ограниченность итераций.** Repair loop должен быть bounded, например не более 3 итераций.

---

## 8. Архитектурное решение

## 8.1. Общий принцип

Рекомендуемая архитектура — **offline synthesis -> compile -> validate -> cache**. Она опирается на наблюдение, что generated code в задаче интероперабельности можно переиспользовать детерминированно и без новых LLM-вызовов, в отличие от прямой генерации результата на каждом шаге [@falcao2025interop].

## 8.2. Этап 0. Детерминированный профилировщик `L0`

Перед обращением к LLM формат нужно детерминированно профилировать.

Для `JSON` собираются:

- пути до полей;
- типы значений;
- nullable ratio;
- вложенность;
- массивы и их кардинальность;
- повторяющиеся ключи и возможные идентификаторы.

Для `CSV` собираются:

- имена столбцов;
- inferred types;
- доля пропусков;
- кандидаты в enum;
- диапазоны и статистики;
- representative rows.

Работы по schema matching и end-to-end integration показывают, что LLM полезнее давать не сырой датасет, а **имена полей, summaries, representative values и целевой schema context** [@buss2025scalable; @steiner2026e2edi].

## 8.3. Этап 1. Построение `SourceSchemaSpec`

На этом шаге LLM получает:

- профиль `L0`;
- 5–20 representative samples;
- optional `format_hint`;
- задачу: построить каноническое описание источника.

Важное правило: модель должна восстанавливать не просто синтаксис, а **семантику полей**, гранулярность записи, единицы измерения и связи между полями. Работы по intent-aware schema generation показывают, что явный `intent`/`format hint` уменьшает неоднозначность и улучшает восстановление схемы [@padmakumar2025intent].

Чтобы снизить нестабильность, для нового формата используется ансамбль prompt-вариантов и агрегирование результатов. Это прямо соответствует выводам о чувствительности schema mapping к phrasing/structure и полезности sampling+aggregation [@buss2025scalable].

## 8.4. Этап 2. Построение `TargetSchemaCard`

`Pydantic`-модели `L1` остаются исполнимой истиной, но для LLM нужен отдельный слой описания. Поэтому для каждого класса и поля формируется `TargetSchemaCard`, где фиксируются:

- имя поля;
- тип;
- обязательность;
- краткое семантическое описание;
- enum / диапазоны / допустимые значения;
- example values;
- cross-field constraints.

Такой шаг опирается на выводы PARSE и schema-first работ: обычный schema contract, удобный человеку, часто недостаточно информативен для LLM; дополнительные schema-oriented descriptions и structured diagnostics повышают надежность [@shrimal2025parse; @sigdel2026schemafirst].

## 8.5. Этап 3. Генерация `MappingIR`

LLM не должен сразу генерировать произвольный Python-код. Вместо этого он должен выпустить `MappingIR` — ограниченный DSL преобразования.

Минимальный набор операций:

- `copy` / `rename`;
- `cast`;
- `map_enum`;
- `unit_convert`;
- `split` / `merge`;
- `nest` / `unnest`;
- `derive(expr)`;
- `default`;
- `validate(predicate)`;
- `drop`.

Использование constrained DSL согласуется с результатами Anka: специально спроектированный язык с явными шагами и промежуточными переменными уменьшает число ошибок при многошаговых преобразованиях и оказывается надежнее свободного Python-кода [@almazrouei2025anka].

## 8.6. Этап 4. Компиляция `MappingIR` в Python-конвертер

Детерминированный компилятор преобразует `MappingIR` в:

- Python-модуль конвертера;
- `Pydantic`-валидацию результата;
- unit-тесты;
- property-тесты;
- golden tests на размеченных примерах.

Этот шаг должен быть полностью детерминированным и повторяемым.

## 8.7. Этап 5. Валидация и bounded repair

После компиляции конвертер проходит три класса проверок:

1. **Structural validity** — выход соответствует `Pydantic`/JSON Schema.
2. **Execution validity** — код исполняется без ошибок.
3. **Semantic validity** — значения корректно отражают исходный `L0`.

Такое разделение обязательно, потому что свежие бенчмарки показывают: формально валидный structured output еще не гарантирует корректную семантику, а на широких схемах frontier-модели остаются нестабильными [@geng2025jsonschemabench; @ferguson2026extractbench].

Если тесты не проходят, запускается bounded repair loop. В repair-подсказку передаются:

- лог ошибки;
- failing example;
- проблемное правило `MappingIR`;
- diff между ожидаемым и фактическим `L1`.

Использование execution feedback и staged generation опирается на execution-guided code generation и planning-driven workflows [@lavon2025egcfg].

## 8.8. Этап 6. Drift detection и patch adaptation

На новых поступлениях вычисляется `schema fingerprint`:

- множество путей/столбцов;
- типы;
- nullable ratio;
- enum-значения;
- units;
- кардинальность;
- presence/absence критических полей.

Затем формируется `DriftReport` одного из типов:

- `additive-compatible`;
- `rename-compatible`;
- `semantic-change`;
- `breaking-change`.

Для совместимого дрейфа сначала применяются детерминированные fallback-правила, а затем при необходимости — patch-generation. Patch-подход лучше полной регенерации, поскольку изменения локализуются и дешевле верифицируются [@duanis2025jsonwhisperer].

---

## 9. Псевдоалгоритм

```text
Input:
  samples_L0, optional format_hint, target_pydantic_models
Output:
  ConverterPackage, SourceSchemaSpec, MappingIR, optional Patch

1. profile <- deterministic_profile(samples_L0)
2. source_schema_candidates <- LLM_schema_induction(profile, samples_L0, format_hint, budget=K_schema)
3. SourceSchemaSpec <- aggregate_and_validate(source_schema_candidates)
4. TargetSchemaCard <- build_target_schema_card(target_pydantic_models)
5. mapping_candidates <- LLM_mapping(SourceSchemaSpec, TargetSchemaCard, conversion_hint, budget=K_mapping)
6. MappingIR <- select_best_mapping(mapping_candidates)
7. ConverterPackage <- compile(MappingIR)
8. report <- run_acceptance_suite(ConverterPackage)
9. if report.failed and repair_budget_not_exceeded:
       Patch <- LLM_repair(report, MappingIR)
       MappingIR <- apply(Patch)
       goto step 7
10. publish(ConverterPackage, SourceSchemaSpec, MappingIR)
11. for each new incoming L0 object:
       if drift_detected(object, SourceSchemaSpec):
           emit DriftReport
           optionally run patch pipeline offline
       else:
           return ConverterPackage.convert(object)
```

---

## 10. Подзадачи (work packages)

## WP-1. Профилировщик и сбор representative samples

### Цель

Реализовать детерминированный модуль, который строит устойчивый профиль нового `L0`-формата.

### Результат

- `profile_builder.py`
- `sample_selector.py`
- `schema_fingerprint.py`
- набор example reports

### Критерий готовности

Для любого входного `CSV/JSON` можно автоматически получить машиночитаемый профиль и fingerprint.

---

## WP-2. Генерация `SourceSchemaSpec`

### Цель

Сконструировать prompt contract и агрегатор, который превращает профиль `L0` в каноническое описание формата.

### Результат

- `source_schema_spec.py`
- prompt templates
- aggregation rules
- confidence scoring

### Критерий готовности

На тестовых форматах система стабильно порождает структурированную спецификацию с полями, типами, кратностью и алиасами.

---

## WP-3. Генерация `TargetSchemaCard`

### Цель

Автоматически строить LLM-ориентированное описание `L1` на основе `Pydantic`-моделей.

### Результат

- `target_schema_card_builder.py`
- exporter из `Pydantic` в `TargetSchemaCard`

### Критерий готовности

Для каждой `Pydantic`-модели есть компактное и однозначное LLM-представление с examples и constraints.

---

## WP-4. Дизайн `MappingIR`

### Цель

Спроектировать промежуточный DSL преобразований, достаточно выразительный для большинства `L0 -> L1` кейсов, но ограниченный для надежной генерации.

### Результат

- `mapping_ir.md`
- JSON Schema / `Pydantic`-модель для `MappingIR`
- каталог допустимых операций

### Критерий готовности

`MappingIR` покрывает rename/cast/default/nesting/enum mapping/unit conversion/derived fields и может быть провалидирован автоматически.

---

## WP-5. LLM-синтез `MappingIR`

### Цель

Научить pipeline генерировать `MappingIR` из `SourceSchemaSpec` и `TargetSchemaCard`.

### Результат

- prompt templates для mapping synthesis
- selector/ranker для нескольких кандидатов
- error-aware repair prompts

### Критерий готовности

На pilot-наборе форматов система генерирует корректный `MappingIR`, который компилируется и проходит базовые тесты.

---

## WP-6. Компилятор `MappingIR -> Python`

### Цель

Построить детерминированный транслятор промежуточного IR в Python-конвертер.

### Результат

- `compiler.py`
- runtime library для операций `cast`, `unit_convert`, `map_enum`, `derive`
- template генерации тестов

### Критерий готовности

Для валидного `MappingIR` всегда строится исполняемый Python-модуль, который не требует LLM при работе.

---

## WP-7. Acceptance suite

### Цель

Построить единый контур приемки качества конвертера.

### Результат

- `golden_tests/`
- `property_tests/`
- `semantic_assertions.py`
- `evaluation_report.md`

### Критерий готовности

Система умеет измерять минимум:

- structural validity;
- execution success;
- field-level semantic correctness;
- converter coverage;
- runtime latency;
- число repair-итераций.

---

## WP-8. Drift detection и patch-generation

### Цель

Добавить контур обнаружения изменений входного формата и локальной адаптации.

### Результат

- `drift_detector.py`
- `patch_ir.py`
- сценарии additive/rename/semantic drift

### Критерий готовности

На synthetic и реальных drift-сценариях система различает совместимые и разрушающие изменения, а для совместимых выпускает patch без полной регенерации.

---

## WP-9. Экспериментальный контур и сравнение с baseline

### Цель

Подготовить воспроизводимое экспериментальное сравнение архитектуры с альтернативами.

### Baselines

1. ручной rule-based converter;
2. `DIRECT`-LLM конвертация каждого объекта;
3. прямой `codegen` без промежуточного `MappingIR`;
4. при наличии данных — частично ручной semi-automatic mapping.

### Метрики

- точность по обязательным полям;
- macro/micro field accuracy;
- pass@1 для генерации рабочего конвертера;
- число repair-итераций;
- доля случаев с drift, решенных patch-ом;
- стоимость подготовки конвертера;
- стоимость одной эксплуатационной конвертации.

### Критерий готовности

Есть воспроизводимый benchmark и таблица, показывающая, в каких сценариях offline codegen-подход выигрывает по надежности и стоимости эксплуатации.

---

## 11. Алгоритмические решения, которые нужно явно реализовать

## 11.1. Representative sampling

Выбирать не случайные записи, а набор примеров, который покрывает:

- полные записи;
- записи с редкими полями;
- альтернативные ветви вложенных структур;
- значения-кандидаты на enum/единицы.

## 11.2. Ensemble prompting + aggregation

Для schema induction и mapping synthesis использовать несколько prompt-вариантов и агрегирование. Это особенно важно из-за чувствительности schema mapping к phrasing и input structure [@buss2025scalable].

## 11.3. Budgeted evidence packing

В prompt не следует передавать весь источник и всю целевую схему целиком. Вместо этого нужен компактный пакет наиболее дискриминирующего контекста. Это согласуется с идеей budgeted evidence packing из ConStruM [@chen2026construm].

## 11.4. Schema-first contracts

Все ответы модели на управляющих этапах должны быть строго типизированы: `SourceSchemaSpec`, `MappingIR`, `Patch`. Schema-first interfaces и structured diagnostics повышают надежность под ограниченным бюджетом взаимодействия [@sigdel2026schemafirst].

## 11.5. Bounded repair

Repair должен вносить локальные изменения в `MappingIR`, а не заново синтезировать весь конвертер. Для structured generation staged-режимы и patching обычно надежнее слепой полной регенерации [@reddy2026dccd; @duanis2025jsonwhisperer].

---

## 12. Критерии приемки крупной задачи

Крупная задача считается выполненной, если выполнены все условия ниже.

### 12.1. По архитектуре

- реализован полный pipeline `profile -> schema -> IR -> compile -> validate -> publish`;
- runtime-конвертация выполняется без LLM;
- все артефакты версионируются.

### 12.2. По качеству

- на pilot-наборе форматов конвертеры проходят `Pydantic`-валидацию;
- на golden set достигается высокая семантическая точность;
- repair loop укладывается в ограниченный бюджет итераций;
- drift detector отделяет совместимые изменения от несовместимых.

### 12.3. По научному результату

- есть сравнение с baseline-подходами;
- показано, что промежуточный `MappingIR` и compile-once режим повышают надежность/воспроизводимость;
- показано, что patch-based adaptation дешевле и стабильнее полной регенерации хотя бы на части drift-сценариев.

---

## 13. Основные риски и способы снижения

### Риск 1. Формальная валидность без семантической корректности

Свежие structured-output benchmarks показывают, что валидный JSON еще не означает корректную экстракцию или корректное отображение значений [@ferguson2026extractbench; @geng2025jsonschemabench].

**Митигировать:** golden tests, field-level assertions, unit tests для преобразования единиц и enum mapping.

### Риск 2. Нестабильность schema matching из-за phrasing

LLM-чувствительность к phrasing и структуре входа уже наблюдается в schema mapping [@buss2025scalable].

**Митигировать:** ensemble prompts, aggregation, confidence scoring.

### Риск 3. Потеря семантики при жестком constrained decoding

Стандартное constrained decoding может улучшать валидность, но ухудшать семантическую траекторию генерации; staged strategies вроде DCCD снимают часть этой проблемы [@reddy2026dccd].

**Митигировать:** использовать constrained outputs только для управляющих артефактов малого размера и совмещать их с draft/planning стадией.

### Риск 4. Широкие/сложные схемы плохо переносятся

На больших схемах reliability падает даже у frontier-моделей [@ferguson2026extractbench].

**Митигировать:** разбиение задачи на sub-mappings, budgeted context packing, staged validation.

### Риск 5. Полная регенерация конвертера при мелком дрейфе

Это ведет к лишней стоимости и регрессиям.

**Митигировать:** patch-based editing и локальная эволюция `MappingIR` [@duanis2025jsonwhisperer].

---

## 14. Ожидаемые научные результаты

1. **Алгоритм offline-генерации конвертеров `L0 -> L1`** с конечным числом LLM-вызовов на формат.
2. **Промежуточный формализм `MappingIR`** для контролируемого синтеза преобразований.
3. **Контур многоуровневой валидации**, разделяющий структурную, исполнимую и семантическую корректность.
4. **Алгоритм patch-based адаптации к дрейфу формата**.
5. **Экспериментальное сравнение** с runtime prompting и прямым codegen без IR.

---

## 15. Краткая формулировка для постановки в трекер

**Epic:** Разработать offline pipeline генерации конвертеров `L0 -> L1` на основе LLM, который один раз анализирует новый формат, синтезирует и компилирует детерминированный Python-конвертер, валидирует его на структурном и семантическом уровнях, а затем эксплуатирует без LLM; при изменении входного формата система должна детектировать дрейф и локально выпускать patch к конвертеру вместо полной регенерации.

---

## 16. Рекомендуемые источники для обоснования

Ключевые выводы, на которых основана постановка:

- schema mapping через LLM требует sampling/aggregation и чувствителен к phrasing [@buss2025scalable];
- end-to-end конфигурирование data integration artifacts через LLM уже возможно и может давать качество, сопоставимое с human-designed pipelines [@steiner2026e2edi];
- schema optimization и schema-first interfaces повышают надежность структурированной генерации [@shrimal2025parse; @sigdel2026schemafirst];
- constrained decoding полезен, но не решает задачу семантической корректности сам по себе [@geng2025jsonschemabench; @reddy2026dccd];
- большие сложные схемы по-прежнему являются трудным случаем даже для сильных моделей [@ferguson2026extractbench];
- DSL/IR для data transformation делает генерацию кода надежнее [@almazrouei2025anka];
- patch-based editing лучше полной регенерации для локальных изменений структуры [@duanis2025jsonwhisperer].

---

## 17. BibTeX

```bibtex
@article{falcao2025interop,
  title   = {Evaluating the Effectiveness of LLM-based Interoperability},
  author  = {Falc\~ao, Rodrigo and Schweitzer, Stefan and Siebert, Julien and Calvet, Emily and Elberzhager, Frank},
  journal = {arXiv preprint arXiv:2510.23893},
  year    = {2025}
}

@article{steiner2026e2edi,
  title   = {Automatic End-to-End Data Integration using Large Language Models},
  author  = {Steiner, Aaron and Bizer, Christian},
  journal = {arXiv preprint arXiv:2603.10547},
  year    = {2026}
}

@article{buss2025scalable,
  title   = {Towards Scalable Schema Mapping using Large Language Models},
  author  = {Buss, Christopher and Safari, Mahdis and Termehchy, Arash and Lee, Stefan and Maier, David},
  journal = {arXiv preprint arXiv:2505.24716},
  year    = {2025}
}

@article{chen2026construm,
  title   = {ConStruM: A Structure-Guided LLM Framework for Context-Aware Schema Matching},
  author  = {Chen, Houming and Zhang, Zhe and Jagadish, H. V.},
  journal = {arXiv preprint arXiv:2601.20482},
  year    = {2026}
}

@inproceedings{shrimal2025parse,
  title     = {PARSE: LLM Driven Schema Optimization for Reliable Entity Extraction},
  author    = {Shrimal, Anubhav and Jain, Aryan and Chowdhury, Soumyajit and Yenigalla, Promod},
  booktitle = {Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing: Industry Track},
  pages     = {2749--2763},
  year      = {2025},
  doi       = {10.18653/v1/2025.emnlp-industry.184}
}

@inproceedings{padmakumar2025intent,
  title     = {Intent-aware Schema Generation and Refinement for Literature Review Tables},
  author    = {Padmakumar, Vishakh and Chang, Joseph Chee and Lo, Kyle and Downey, Doug and Naik, Aakanksha},
  booktitle = {Findings of the Association for Computational Linguistics: EMNLP 2025},
  pages     = {23450--23472},
  year      = {2025},
  doi       = {10.18653/v1/2025.findings-emnlp.1274}
}

@article{geng2025jsonschemabench,
  title   = {JSONSchemaBench: A Rigorous Benchmark of Structured Outputs for Language Models},
  author  = {Geng, Saibo and Cooper, Hudson and Moskal, Micha\l{} and Jenkins, Samuel and Berman, Julian and Ranchin, Nathan and West, Robert and Horvitz, Eric and Nori, Harsha},
  journal = {arXiv preprint arXiv:2501.10868},
  year    = {2025}
}

@article{ferguson2026extractbench,
  title   = {ExtractBench: A Benchmark and Evaluation Methodology for Complex Structured Extraction},
  author  = {Ferguson, Nick and Pennington, Josh and Beghian, Narek and Mohan, Aravind and Kiela, Douwe and Agrawal, Sheshansh and Nguyen, Thien Hang},
  journal = {arXiv preprint arXiv:2602.12247},
  year    = {2026}
}

@article{reddy2026dccd,
  title   = {Draft-Conditioned Constrained Decoding for Structured Generation in LLMs},
  author  = {Reddy, Avinash and Walker, Thayne T. and Ide, James S. and Bedi, Amrit Singh},
  journal = {arXiv preprint arXiv:2603.03305},
  year    = {2026}
}

@article{almazrouei2025anka,
  title   = {Anka: A Domain-Specific Language for Reliable LLM Code Generation},
  author  = {Al Mazrouei, Saif Khalfan Saif},
  journal = {arXiv preprint arXiv:2512.23214},
  year    = {2025}
}

@article{lavon2025egcfg,
  title   = {Execution Guided Line-by-Line Code Generation},
  author  = {Lavon, Boaz and Katz, Shahar and Wolf, Lior},
  journal = {arXiv preprint arXiv:2506.10948},
  year    = {2025}
}

@article{duanis2025jsonwhisperer,
  title   = {JSON Whisperer: Efficient JSON Editing with LLMs},
  author  = {Duanis, Sarel and Greenstein-Messica, Asnat and Habba, Eliya},
  journal = {arXiv preprint arXiv:2510.04717},
  year    = {2025}
}

@article{neubauer2025jsonschema,
  title   = {AI-assisted JSON Schema Creation and Mapping},
  author  = {Neubauer, Felix and Pleiss, J\"urgen and Uekermann, Benjamin},
  journal = {arXiv preprint arXiv:2508.05192},
  year    = {2025}
}

@article{sigdel2026schemafirst,
  title   = {Schema First Tool APIs for LLM Agents: A Controlled Study of Tool Misuse, Recovery, and Budgeted Performance},
  author  = {Sigdel, Akshey and Baral, Rista},
  journal = {arXiv preprint arXiv:2603.13404},
  year    = {2026}
}
```
