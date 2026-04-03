# ai-converter

`ai-converter` is a deterministic Python library for preparing free-form `L0` schedule data for later conversion into a fixed `L1` DSL.

At the current stage the library gives you two main building blocks:

- profiling raw `CSV`, `JSON`, and `JSONL` inputs into a stable `ProfileReport`
- building schema contracts and compact evidence bundles on top of that profile

Test-running instructions live in [tests/README.md](tests/README.md).

## Installation

The package requires Python `>=3.11`.

Install it in editable mode from the repository root:

```bash
python -m pip install -e .
```

## Use The Profiling API

The profiling layer lives in `src/llm_converter/profiling/` and exposes a simple entry point through `llm_converter.profiling`.

```python
from llm_converter.profiling import build_profile_report

report = build_profile_report("tests/fixtures/profiling/projects.json")

print(report.schema_fingerprint)
print(report.record_count)
print(report.field_profiles[0].path)
```

What you get back:

- normalized source metadata
- path-based field statistics
- deterministic representative samples
- a stable schema fingerprint that ignores row reordering

## Use The Schema API

The schema contract layer lives in `src/llm_converter/schema/`.

It helps you:

- describe source-side structure with `SourceSchemaSpec`
- normalize and merge schema candidates deterministically
- export Pydantic target models into compact `TargetSchemaCard` objects
- compress a `ProfileReport` into a budgeted evidence bundle for later LLM stages

### Example: pack evidence from a profile

```python
from llm_converter.profiling import build_profile_report
from llm_converter.schema import pack_profile_evidence

report = build_profile_report("tests/fixtures/profiling/projects.json")
bundle = pack_profile_evidence(
    report,
    budget=1400,
    mode="balanced",
    format_hint="project schedule data",
)

print(bundle.summary.field_count)
print(bundle.estimated_size)
print(bundle.truncated)
```

### Example: build a target schema card from a Pydantic model

```python
from pydantic import BaseModel, Field

from llm_converter.schema import build_target_schema_card


class DemoTask(BaseModel):
    id: str = Field(description="Task identifier")
    duration_days: int | None = Field(default=None, description="Planned duration")


card = build_target_schema_card(DemoTask)

print(card.model_name)
print(card.fields[0].path)
print(card.fields[0].description)
```

## Package Layout

- `src/llm_converter/profiling/` contains the deterministic profiling layer
- `src/llm_converter/schema/` contains schema contracts and evidence packing
- `docs/architecture/profiling.md` documents the profiling design
- `docs/architecture/schema_contracts.md` documents the schema contract layer

## Project Notes

- `dsl-core/` is treated as an external, read-only reference for the fixed `L1` DSL.
- The current library scope is deterministic preparation and schema-contract work; live LLM calls are intentionally out of scope here.
- If you need commands for running the test suites, fixtures, or focused verification flows, use [tests/README.md](tests/README.md).
