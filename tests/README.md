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

### TASK-01 profiling

Fixtures:

- `tests/fixtures/profiling/`

Tests:

- `tests/unit/profiling/`

Command:

```bash
python -m pytest tests/unit/profiling -q -p no:cacheprovider
```

### TASK-02 schema contracts

Fixtures:

- `tests/fixtures/schema/`

Tests:

- `tests/unit/schema/`

Command:

```bash
python -m pytest tests/unit/schema -q -p no:cacheprovider
```

### TASK-03 mapping ir

Fixtures:

- inline deterministic fixtures in `tests/unit/mapping_ir/`

Tests:

- `tests/unit/mapping_ir/`
- includes offline checks for `FakeLLMAdapter` and `OpenAILLMAdapter` via injected fake client objects

Command:

```bash
python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider
```

### TASK-04 compiler and validation

Tests:

- `tests/unit/compiler/`
- `tests/unit/validation/`

Smoke integration tests:

- `tests/integration/converter_pipeline/`

Command:

```bash
python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider
```

### TASK-05 drift and evaluation

Fixtures:

- `tests/fixtures/drift/`

Tests:

- `tests/unit/drift/`
- `tests/unit/evaluation/`

Command:

```bash
python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider
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
- `tests/fixtures/drift/` contains synthetic baseline and drifted source payloads for TASK-05

## Notes

- `dsl-core/` is external reference code and should not be modified while working on profiling or schema tests.
- TASK-05 benchmark tests should keep report output inside repo-local writable paths when temporary artifacts are needed.
- If you only change documentation, running tests is optional.
