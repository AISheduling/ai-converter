# ai-converter

`ai-converter` is a deterministic Python library for preparing free-form `L0` schedule data for later conversion into a fixed `L1` DSL.

At the current stage the library gives you three main building blocks:

- profiling raw `CSV`, `JSON`, and `JSONL` inputs into a stable `ProfileReport`
- building schema contracts and compact evidence bundles on top of that profile
- synthesizing and validating `MappingIR` candidates with file-backed prompts and a fake LLM adapter
- compiling valid `MappingIR` programs into pure Python converters with offline acceptance validation

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

## Use The Mapping IR API

`TASK-03` adds an offline LLM-facing layer under `src/llm_converter/llm/` and `src/llm_converter/mapping_ir/`.

It helps you:

- render versioned prompts from `ProfileReport`, `SourceSchemaSpec`, and `TargetSchemaCard`
- validate `MappingIR` candidates before any runtime compilation exists
- rank multiple fake-backed candidates by structural validity and target coverage
- build bounded repair prompts from failing fixtures
- switch between `FakeLLMAdapter` for offline tests and `OpenAILLMAdapter` for real OpenAI-backed calls

### Example: rank fake-backed mapping candidates

```python
from llm_converter.llm import FakeLLMAdapter, FakeLLMReply
from llm_converter.mapping_ir import MappingSynthesizer
from llm_converter.schema.source_spec_models import SourceFieldSpec, SourceSchemaSpec
from llm_converter.schema.target_card_builder import build_target_schema_card
from pydantic import BaseModel


class DemoTask(BaseModel):
    id: str
    name: str | None = None


class DemoTarget(BaseModel):
    task: DemoTask


source_schema = SourceSchemaSpec(
    source_name="demo",
    source_format="json",
    root_type="list",
    fields=[
        SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str"),
        SourceFieldSpec(path="task_name", semantic_name="task_name", dtype="str"),
    ],
)
target_schema = build_target_schema_card(DemoTarget)

adapter = FakeLLMAdapter(
    structured_replies=[
        FakeLLMReply(
            parsed_payload={
                "source_refs": [
                    {"id": "src_task_id", "path": "task_id", "dtype": "str"},
                    {"id": "src_task_name", "path": "task_name", "dtype": "str"},
                ],
                "steps": [
                    {"id": "copy_task_id", "operation": {"kind": "copy", "source_ref": "src_task_id"}},
                    {"id": "copy_task_name", "operation": {"kind": "copy", "source_ref": "src_task_name"}},
                ],
                "assignments": [
                    {"step_id": "copy_task_id", "target_path": "task.id"},
                    {"step_id": "copy_task_name", "target_path": "task.name"},
                ],
            }
        )
    ]
)

result = MappingSynthesizer(adapter).synthesize_mapping(
    source_schema,
    target_schema,
    candidate_count=1,
)

print(result.best_index)
print(result.best_candidate.assignments[0].target_path)
```

### Example: create a real OpenAI-backed adapter

```python
from llm_converter.llm import OpenAILLMAdapter

adapter = OpenAILLMAdapter(
    model="gpt-5.4-mini",
    api_key="YOUR_OPENAI_API_KEY",
)
```

The OpenAI adapter uses the Responses API under the hood and keeps imports lazy, so offline tests can still run without network access by using injected fake clients.

## Use The Compiler And Validation API

`TASK-04` adds deterministic execution under `src/llm_converter/compiler/` and `src/llm_converter/validation/`.

It helps you:

- compile a validated `MappingIR` program into an importable Python module
- execute the compiled converter without any live LLM calls
- validate the converted payload structurally with a target `Pydantic` model
- run semantic assertions and bounded repair loops offline with fake patch strategies

### Example: compile a `MappingIR` program and validate one output

```python
from pydantic import BaseModel

from llm_converter.compiler import compile_mapping_ir
from llm_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from llm_converter.validation import validate_structural_output


class DemoTask(BaseModel):
    id: str


class DemoTarget(BaseModel):
    task: DemoTask


program = MappingIR(
    source_refs=[SourceReference(id="src_task_id", path="task_id", dtype="str")],
    steps=[MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id"))],
    assignments=[TargetAssignment(step_id="copy_task_id", target_path="task.id")],
)

compiled = compile_mapping_ir(program)
payload = compiled.convert({"task_id": "T-1"})
result = validate_structural_output(payload, DemoTarget)

print(payload)
print(result.valid)
```

## Package Layout

- `src/llm_converter/profiling/` contains the deterministic profiling layer
- `src/llm_converter/schema/` contains schema contracts and evidence packing
- `src/llm_converter/llm/` contains prompt rendering and adapter contracts
- `src/llm_converter/mapping_ir/` contains MappingIR models, validation, ranking, and repair helpers
- `src/llm_converter/compiler/` contains deterministic code generation and module loading
- `src/llm_converter/validation/` contains structural, semantic, acceptance, and repair-loop validation
- `prompts/` contains versioned prompt template files
- `docs/architecture/profiling.md` documents the profiling design
- `docs/architecture/schema_contracts.md` documents the schema contract layer
- `docs/prompts/mapping_ir.md` documents the MappingIR prompt layer
- `docs/architecture/compiler_and_validation.md` documents the execution and validation design

## Project Notes

- `dsl-core/` is treated as an external, read-only reference for the fixed `L1` DSL.
- The current library scope is deterministic preparation and schema-contract work; live LLM calls are intentionally out of scope here.
- If you need commands for running the test suites, fixtures, or focused verification flows, use [tests/README.md](tests/README.md).
