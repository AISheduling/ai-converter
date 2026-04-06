# Tests

This file contains the repository's test-running instructions.

The test tree exists to prove that each pipeline stage stays deterministic, offline, and safe to run without live LLM calls.

Run all commands from the repository root:

`ai-converter`

## General Rules

- Use Python `>=3.11`.
- Prefer `python -m pytest`.
- Use `-p no:cacheprovider` for the focused suites used in this repository.
- Tests must run without network access and without live LLM calls.


## Focused Test Suites

### Profiling

Fixtures:

- `tests/fixtures/profiling/`

Tests:

- `tests/unit/profiling/`

Command:

```bash
python -m pytest tests/unit/profiling -q -p no:cacheprovider
```

### Schema contracts

Fixtures:

- `tests/fixtures/schema/`

Tests:

- `tests/unit/schema/`

Command:

```bash
python -m pytest tests/unit/schema -q -p no:cacheprovider
```

### Mapping IR

Fixtures:

- inline deterministic fixtures in `tests/unit/mapping_ir/`

Tests:

- `tests/unit/mapping_ir/`
- includes offline checks for `FakeLLMAdapter` and `OpenAILLMAdapter` via injected fake client objects
- includes prompt/reply trace export checks through `LLMResponse.to_trace_artifact()`

Command:

```bash
python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider
```

### Compiler and validation

Tests:

- `tests/unit/compiler/`
- `tests/unit/validation/`

Smoke integration tests:

- `tests/integration/converter_pipeline/`
- includes the from-scratch example smoke run through an injected fake OpenAI client

Coverage notes:

- verifies the explicit `ConverterPackage` contract
- verifies deterministic manifest/export behavior
- keeps the compiled converter, acceptance, and repair-loop path offline
- verifies acceptance-report export and per-attempt repair trace export stay deterministic

Command:

```bash
python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider
```

### Drift and evaluation

Fixtures:

- `tests/fixtures/drift/`

Tests:

- `tests/unit/drift/`
- `tests/unit/evaluation/`

Command:

```bash
python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider
```

### Synthetic benchmark foundation

Fixtures:

- `tests/fixtures/synthetic_benchmark/bundles/`
- `tests/fixtures/synthetic_benchmark/drift/`
- `tests/fixtures/synthetic_benchmark/llm_templates/`

Tests:

- `tests/unit/synthetic_benchmark/`
- includes heterogeneous rendering and synthetic drift coverage under `tests/unit/synthetic_benchmark/drift/`
- `tests/unit/synthetic_benchmark/generators_llm/`
- includes offline cache, prompt, and bounded-retry coverage for LLM-assisted template generation

Command:

```bash
python -m pytest tests/unit/synthetic_benchmark -q -p no:cacheprovider
```

LLM-template generator command:

```bash
python -m pytest tests/unit/synthetic_benchmark/generators_llm -q -p no:cacheprovider
```

## Combined Focused Run

Use this when you touch the offline pipeline from mapping-ir through compiled execution:

```bash
python -m pytest tests/unit/profiling tests/unit/schema tests/unit/mapping_ir tests/unit/compiler tests/unit/validation tests/unit/drift tests/unit/evaluation tests/integration/converter_pipeline -q -p no:cacheprovider
```

## Alternative With Poetry

### Schema only

```bash
poetry run python -m pytest tests/unit/schema -q -p no:cacheprovider
```

### Profiling and schema together

```bash
poetry run python -m pytest tests/unit/profiling tests/unit/schema -q -p no:cacheprovider
```

### Mapping ir only

```bash
poetry run python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider
```

### Compiler, validation, and integration

```bash
poetry run python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider
```

### Drift and evaluation only

```bash
poetry run python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider
```

## Test Layout

- `tests/conftest.py` contains shared pytest configuration for the repository
- `tests/unit/` contains focused unit suites
- `tests/integration/` contains smoke integration suites for compiled execution and validation
- `tests/fixtures/` contains deterministic input data used by tests
- `tests/fixtures/drift/` contains synthetic baseline and drifted source payloads for drift and evaluation tests
- `tests/fixtures/synthetic_benchmark/bundles/` contains repo-local fixture roots for persisted synthetic bundles
- `tests/fixtures/synthetic_benchmark/drift/` contains deterministic drift specs and lineage-oriented synthetic drift fixtures
- `tests/fixtures/synthetic_benchmark/llm_templates/` contains deterministic accepted-template and cache fixtures

## Notes

- `dsl-core/` is external reference code and should not be modified while working on profiling or schema tests.
- Benchmark tests should keep report output inside repo-local writable paths when temporary artifacts are needed.
- If you only change documentation, running tests is optional.
