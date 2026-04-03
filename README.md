# ai-converter

Deterministic tooling for converting free-form `L0` schedule descriptions into a fixed `L1` DSL in later tasks.

## TASK-01 Profiling

`TASK-01` adds a profiling layer under `src/llm_converter/profiling/` that reads `CSV`, `JSON`, and `JSONL` inputs and produces a normalized `ProfileReport`.

The profiling flow is:

1. Load raw input through `loaders.py`.
2. Flatten records into path-based observations such as `owner.name` or `tasks[].id`.
3. Aggregate field statistics and select deterministic representative samples.
4. Compute a stable schema fingerprint that ignores row ordering but changes on structural changes.

Relevant fixtures and tests live in:

- `tests/fixtures/profiling/`
- `tests/unit/profiling/`

Run the focused test suite with:

```bash
python -m pytest tests/unit/profiling -q -p no:cacheprovider
```

This repository is building an offline `L0 -> L1` converter pipeline. `TASK-01` adds the first deterministic layer: profiling raw `CSV`, `JSON`, and `JSONL` inputs into a canonical `ProfileReport`.

## Profiling package

The profiling implementation lives under `src/llm_converter/profiling/` and currently covers:

- input loading for `CSV`, `JSON`, and `JSONL`
- path and field statistics
- deterministic representative sampling
- stable schema fingerprinting

`dsl-core/` remains an external reference for the target DSL and is not modified by this task.

## Local test command

Run the focused profiling checks with:

```bash
pytest tests/unit/profiling -q
```

Fixture inputs for the profiling layer live in `tests/fixtures/profiling/`, and a short design note lives in `docs/architecture/profiling.md`.

## TASK-02 Schema Contracts

`TASK-02` adds a schema-first package under `src/llm_converter/schema/`:

- `SourceSchemaSpec` models and deterministic normalization/aggregation helpers
- `TargetSchemaCard` export from nested Pydantic L1 models
- budgeted evidence packing from `ProfileReport`

The fixed L1 contract still lives in read-only form under `dsl-core/`.

Relevant paths:

- `src/llm_converter/schema/`
- `tests/unit/schema/`
- `tests/fixtures/schema/`
- `docs/architecture/schema_contracts.md`

Run the focused schema checks with:

```bash
python -m pytest tests/unit/schema -q -p no:cacheprovider
```
