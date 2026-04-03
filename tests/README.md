# Tests

This file contains the repository's test-running instructions.

Run all commands from the repository root:

`C:\Users\muskrat\workspace\ai-converter`

## General Rules

- Use Python `>=3.11`.
- Prefer `python -m pytest`.
- Use `-p no:cacheprovider` for the focused suites used in this repository.
- Tests must run without network access and without live LLM calls.

If you want to use the exact project interpreter that was used for the focused verification runs, it is:

```text
C:\Users\muskrat\AppData\Local\pypoetry\Cache\virtualenvs\ai-converter-BoqDNqnM-py3.11\Scripts\python.exe
```

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

Command:

```bash
python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider
```

## Combined Focused Run

Use this when you touch profiling, schema, and mapping-ir layers together:

```bash
python -m pytest tests/unit/profiling tests/unit/schema tests/unit/mapping_ir -q -p no:cacheprovider
```

## Alternative With The Exact Poetry Interpreter

### Schema only

```bash
C:\Users\mlhak\AppData\Local\pypoetry\Cache\virtualenvs\ai-converter-b-GWvKUj-py3.12\Scripts\python.exe -m pytest tests/unit/schema -q -p no:cacheprovider
```

### Profiling and schema together

```bash
C:\Users\muskrat\AppData\Local\pypoetry\Cache\virtualenvs\ai-converter-BoqDNqnM-py3.11\Scripts\python.exe -m pytest tests/unit/profiling tests/unit/schema -q -p no:cacheprovider
```

### Mapping ir only

```bash
C:\Users\muskrat\AppData\Local\pypoetry\Cache\virtualenvs\ai-converter-BoqDNqnM-py3.11\Scripts\python.exe -m pytest tests/unit/mapping_ir -q -p no:cacheprovider
```

## Test Layout

- `tests/conftest.py` contains shared pytest configuration for the repository
- `tests/unit/` contains focused unit suites
- `tests/fixtures/` contains deterministic input data used by tests

## Notes

- `dsl-core/` is external reference code and should not be modified while working on profiling or schema tests.
- If you only change documentation, running tests is optional.
