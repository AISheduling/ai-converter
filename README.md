# ai-converter

`ai-converter` is a deterministic Python library for preparing free-form `L0` schedule data for later conversion into a fixed `L1` DSL.

It exists to make the early conversion pipeline reproducible before any live model call happens: profile messy inputs, derive stable contracts, synthesize or validate mapping plans offline, and benchmark the resulting converters with deterministic fixtures.

At the current stage the library gives you six main building blocks:

- profiling raw `CSV`, `JSON`, and `JSONL` inputs into a stable `ProfileReport`
- building schema contracts and compact evidence bundles on top of that profile
- synthesizing and validating `MappingIR` candidates with file-backed prompts and a fake LLM adapter
- compiling valid `MappingIR` programs into versioned `ConverterPackage` artifacts with offline acceptance validation
- classifying compatible versus breaking input drift and generating local patches
- benchmarking baseline and compiled converters with deterministic metrics, canonical report exports, and optional timing telemetry

Test-running instructions live in [tests/README.md](tests/README.md).

## Installation

The package requires Python `>=3.11`.

Install it in editable mode from the repository root:

```bash
python -m pip install -e .
```

## Quickstart

Use this shortest-path flow to verify the repository on a fresh checkout:

1. Install the package in editable mode.
2. Run one focused suite:

```bash
poetry run python -m pytest tests/unit/profiling -q -p no:cacheprovider
```

3. Execute one minimal API example:

```python
from ai_converter.profiling import build_profile_report

report = build_profile_report("tests/fixtures/profiling/projects.json")

print(report.record_count)
print(report.schema_fingerprint)
```

If you want the broader verification matrix, use [tests/README.md](tests/README.md).

## From-Scratch Example

If you want one walkthrough that starts from several JSON inputs and one target `Pydantic` model, see [examples/from_scratch_pipeline/README.md](examples/from_scratch_pipeline/README.md).

The example shows how to:

- combine several source JSON examples into one deterministic profiling baseline
- configure OpenAI-compatible `base_url`, `api_token`, and `model` constants inside the example
- synthesize `SourceSchemaSpec` and `MappingIR`, compile a converter, validate converted output, classify compatible source drift, and apply a local compatible patch

Run it from the repository root with:

```bash
python examples/from_scratch_pipeline/run_example.py
```

The repository test suite runs the same path offline through an injected fake OpenAI client, so the example stays verifiable without live credentials.

## Use The Profiling API

The profiling layer lives in `src/ai_converter/profiling/` and exposes a simple entry point through `ai_converter.profiling`.

```python
from ai_converter.profiling import build_profile_report

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

The schema contract layer lives in `src/ai_converter/schema/`.

It helps you:

- describe source-side structure with `SourceSchemaSpec`
- normalize and merge schema candidates deterministically
- export Pydantic target models into compact `TargetSchemaCard` objects
- compress a `ProfileReport` into a budgeted evidence bundle for later LLM stages

If the requested budget cannot even fit the mandatory evidence summary,
`pack_profile_evidence()` raises `EvidenceBudgetExceededError` instead of
returning an oversized bundle with `truncated=True`.

### Example: pack evidence from a profile

```python
from ai_converter.profiling import build_profile_report
from ai_converter.schema import EvidenceBudgetExceededError, pack_profile_evidence

report = build_profile_report("tests/fixtures/profiling/projects.json")
try:
    bundle = pack_profile_evidence(
        report,
        budget=1400,
        mode="balanced",
        format_hint="project schedule data",
    )
except EvidenceBudgetExceededError as error:
    print(error.minimum_size)
else:
    print(bundle.summary.field_count)
    print(bundle.estimated_size)
    print(bundle.truncated)
```

### Example: build a target schema card from a Pydantic model

```python
from pydantic import BaseModel, Field

from ai_converter.schema import build_target_schema_card


class DemoTask(BaseModel):
    id: str = Field(description="Task identifier")
    duration_days: int | None = Field(default=None, description="Planned duration")


card = build_target_schema_card(DemoTask)

print(card.model_name)
print(card.fields[0].path)
print(card.fields[0].description)
```

## Use The Mapping IR API

The offline LLM-facing layer lives under `src/ai_converter/llm/` and `src/ai_converter/mapping_ir/`.

It helps you:

- render versioned prompts from `ProfileReport`, `SourceSchemaSpec`, and `TargetSchemaCard`
- validate `MappingIR` candidates before any runtime compilation exists
- rank multiple fake-backed candidates by structural validity and target coverage
- optionally enforce a centralized `schema` / `mapping` / `repair` LLM call budget with machine-readable accounting
- build bounded repair prompts from failing fixtures
- switch between `FakeLLMAdapter` for offline tests and `OpenAILLMAdapter` for real OpenAI-backed calls
- persist prompt and model reply artifacts through the shared `LLMResponse.to_trace_artifact()` export surface

### Example: rank fake-backed mapping candidates

```python
from ai_converter.llm import FakeLLMAdapter, FakeLLMReply, LLMCallBudgetPolicy
from ai_converter.mapping_ir import MappingSynthesizer
from ai_converter.schema.source_spec_models import SourceFieldSpec, SourceSchemaSpec
from ai_converter.schema.target_card_builder import build_target_schema_card
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

result = MappingSynthesizer(
    adapter,
    budget_policy=LLMCallBudgetPolicy(schema=0, mapping=1, repair=0),
).synthesize_mapping(
    source_schema,
    target_schema,
    candidate_count=1,
)

print(result.best_index)
print(result.best_candidate.assignments[0].target_path)
print(result.budget_accounting.total_used)
```

When a shared budget policy is configured, successful source-schema calls also expose the current machine-readable accounting in `schema_response.metadata["llm_call_budget"]`.
If the next call would exceed the configured stage limit, the library raises `LLMCallBudgetExceededError` before making that extra adapter call, and `error.snapshot` contains the same per-stage accounting for diagnostics.

```python
from ai_converter.llm import LLMCallBudgetExceededError

schema_response = synthesizer.synthesize_source_schema(report)
print(schema_response.metadata["llm_call_budget"]["stages"]["schema"]["used"])

try:
    synthesizer.synthesize_mapping(source_schema, target_schema, candidate_count=3)
except LLMCallBudgetExceededError as error:
    print(error.stage)
    print(error.snapshot.to_dict()["total_used"])
```

### Example: create a real OpenAI-backed adapter

```python
from ai_converter.llm import OpenAILLMAdapter

adapter = OpenAILLMAdapter(
    model="gpt-5.4-mini",
    api_key="YOUR_OPENAI_API_KEY",
)
```

The OpenAI adapter uses the Responses API under the hood and keeps imports lazy, so offline tests can still run without network access by using injected fake clients.
Every shared adapter response now exposes `response.to_trace_artifact()` so callers can persist prompt inputs, raw replies, usage, metadata, and structured errors as deterministic audit artifacts without the library writing files implicitly.

## Use The Compiler And Validation API

Deterministic execution lives under `src/ai_converter/compiler/` and `src/ai_converter/validation/`.

It helps you:

- compile a validated `MappingIR` program into a versioned `ConverterPackage`
- execute the packaged converter without any live LLM calls
- export a deterministic manifest, generated module, and normalized `MappingIR` payload
- validate the converted payload structurally with a target `Pydantic` model
- export acceptance and repair-loop observability artifacts for offline audit
- run semantic assertions and bounded repair loops offline with fake patch strategies
- export acceptance reports with `AcceptanceReport.to_trace_artifact()` and persist per-attempt repair audit traces through `RepairLoopResult.to_trace_artifact()`

### Example: compile a `MappingIR` program and validate one output

```python
from pydantic import BaseModel

from ai_converter.compiler import compile_mapping_ir
from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.validation import validate_structural_output


class DemoTask(BaseModel):
    id: str


class DemoTarget(BaseModel):
    task: DemoTask


program = MappingIR(
    source_refs=[SourceReference(id="src_task_id", path="task_id", dtype="str")],
    steps=[MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id"))],
    assignments=[TargetAssignment(step_id="copy_task_id", target_path="task.id")],
)

package = compile_mapping_ir(program)
payload = package.convert({"task_id": "T-1"})
result = validate_structural_output(payload, DemoTarget)

print(payload)
print(result.valid)
print(package.manifest.artifact_version)
```

Acceptance and repair traces are also exportable for later audit.
`AcceptanceReport.to_trace_artifact()` and `RepairLoopResult.to_trace_artifact()`
produce deterministic JSON-compatible payloads, and `RepairLoopResult` also
exposes `final_decision` plus `attempt_traces` so callers can persist each
failed attempt, its failure bundle, and the patch or stop outcome deterministically.

## Use The Drift And Evaluation APIs

Deterministic drift handling lives under `src/ai_converter/drift/` and reproducible benchmark helpers under `src/ai_converter/evaluation/`.

It helps you:

- classify additive, rename-compatible, semantic, and breaking source drift
- propose local source-schema and `MappingIR` patches without regenerating the whole converter
- run baseline and compiled converters through one benchmark harness
- export canonical JSON, CSV, and Markdown benchmark reports, plus optional timing telemetry

### Example: classify compatible drift and build a local patch

```python
from ai_converter.drift import classify_drift, propose_compatible_patch
from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.profiling import build_profile_report
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec

baseline_report = build_profile_report("tests/fixtures/drift/baseline_schedule.json")
candidate_report = build_profile_report("tests/fixtures/drift/rename_schedule.json")
source_schema = SourceSchemaSpec(
    source_name="schedule",
    source_format="json",
    root_type="list",
    fields=[
        SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str"),
        SourceFieldSpec(path="task_name", semantic_name="task_name", dtype="str"),
        SourceFieldSpec(path="status_text", semantic_name="status_text", dtype="str"),
    ],
)
mapping_ir = MappingIR(
    source_refs=[
        SourceReference(id="src_task_id", path="task_id", dtype="str"),
        SourceReference(id="src_task_name", path="task_name", dtype="str"),
    ],
    steps=[
        MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
        MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
    ],
    assignments=[
        TargetAssignment(step_id="copy_task_id", target_path="task.id"),
        TargetAssignment(step_id="copy_task_name", target_path="task.name"),
    ],
)

drift_report = classify_drift(
    baseline_report,
    candidate_report,
    baseline_schema=source_schema,
)
resolution = propose_compatible_patch(drift_report, source_schema, mapping_ir)

print(drift_report.classification)
print(resolution.compatible)
print(resolution.patch.mapping_ir_operations[0].kind)
```

### Example: run a deterministic benchmark and export reports

```python
from pathlib import Path

from ai_converter.evaluation import (
    BenchmarkCase,
    BenchmarkScenario,
    BenchmarkSubject,
    export_benchmark_reports,
    run_benchmark,
)

subject = BenchmarkSubject.from_converter(
    "compiled-demo",
    lambda record: {
        "task": {"id": record["task_id"], "name": record["task_name"]},
        "status": record["status_text"].lower(),
    },
    kind="compiled",
)

scenario = BenchmarkScenario(
    name="happy-path",
    cases=[
        BenchmarkCase(
            name="case-1",
            record={"task_id": "T-1", "task_name": "Plan", "status_text": "READY"},
            expected_output={"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
            required_fields=["task.id", "status"],
        )
    ],
)

result = run_benchmark([subject], [scenario])
paths = export_benchmark_reports(result, Path("benchmark_artifacts"), stem="task05_demo")

print(paths["json"])
print(paths["markdown"])
```

Canonical `benchmark.json` and `benchmark.csv` omit volatile wall-clock timing
fields so identical deterministic runs can produce reproducible machine-readable
artifacts. If you need timing diagnostics, call
`export_benchmark_reports(..., include_telemetry=True)` and read the separate
`<stem>.telemetry.json` sidecar.

## Use The Synthetic Benchmark Foundation

The deterministic synthetic benchmark foundation lives under
`src/ai_converter/synthetic_benchmark/`.

It helps you:

- sample canonical task scenarios reproducibly from a seed
- render the same scenario into a gold `L1` payload and a configurable `L0` payload
- apply deterministic shape-variant policies so same-type records can render with different source-side field sets
- apply versioned synthetic drift specs to `L0` payloads without changing the canonical scenario
- persist repo-local base and drift bundles with lineage metadata for later drift and benchmark tasks

### Example: sample, render, and persist one bundle

```python
from pathlib import Path

from ai_converter.synthetic_benchmark import (
    BundleStore,
    L0TemplateSpec,
    ScenarioSamplerConfig,
    sample_canonical_scenario,
)

sampled = sample_canonical_scenario(
    7,
    ScenarioSamplerConfig(task_count=2, include_assignees=True, include_tags=True),
)
store = BundleStore()
bundle = store.build_bundle(
    sampled,
    L0TemplateSpec(),
    dataset_id="synthetic-demo",
    bundle_id="bundle-1",
    created_at="2026-04-06T00:00:00+00:00",
)
paths = store.save(bundle, Path("synthetic_bundle"))

print(paths.scenario_path)
print(paths.l0_path)
print(paths.l1_path)
```

### Example: derive one drift bundle from a base bundle

```python
from pathlib import Path

from ai_converter.synthetic_benchmark import (
    AddFieldOperator,
    BundleStore,
    DriftSpec,
    L0TemplateSpec,
    RenameFieldOperator,
    sample_canonical_scenario,
)

store = BundleStore()
base_bundle = store.build_bundle(
    sample_canonical_scenario(7),
    L0TemplateSpec(),
    dataset_id="synthetic-demo",
    bundle_id="bundle-1",
    created_at="2026-04-06T00:00:00+00:00",
)
drift_bundle = store.build_drift_bundle(
    base_bundle,
    DriftSpec(
        drift_id="rename-plus-additive",
        drift_type="mixed",
        severity="low",
        compatibility_class="rename_compatible",
        operators=[
            RenameFieldOperator(
                record_indexes=[0],
                path="task_name",
                new_path="taskName",
            ),
            AddFieldOperator(
                record_indexes=[0],
                path="task_priority",
                value="P2",
            ),
        ],
    ),
    bundle_id="bundle-1-drift",
    created_at="2026-04-06T00:00:00+00:00",
)
paths = store.save(drift_bundle, Path("synthetic_bundle_drift"))

print(paths.drift_manifest_path)
print(paths.lineage_path)
```

## Package Layout

- `src/ai_converter/profiling/` contains the deterministic profiling layer
- `src/ai_converter/schema/` contains schema contracts and evidence packing
- `src/ai_converter/llm/` contains prompt rendering and adapter contracts
- `src/ai_converter/mapping_ir/` contains MappingIR models, validation, ranking, and repair helpers
- `src/ai_converter/compiler/` contains deterministic code generation and module loading
- `src/ai_converter/validation/` contains structural, semantic, acceptance, and repair-loop validation
- `src/ai_converter/drift/` contains drift classification, deterministic heuristics, and local patch application
- `src/ai_converter/evaluation/` contains benchmark metrics, orchestration, and reporting
- `src/ai_converter/synthetic_benchmark/` contains deterministic synthetic scenario sampling, shape variants, drift generation, and lineage-aware bundle storage
- `prompts/` contains versioned prompt template files
- `docs/architecture/profiling.md` documents the profiling design
- `docs/architecture/schema_contracts.md` documents the schema contract layer
- `docs/prompts/mapping_ir.md` documents the MappingIR prompt layer
- `docs/architecture/compiler_and_validation.md` documents the execution and validation design
- `docs/evaluation/benchmark_protocol.md` documents the benchmark and evaluation workflow
- `docs/synthetic_benchmark/architecture.md` documents the synthetic benchmark foundation
- `docs/synthetic_benchmark/drift.md` documents synthetic drift generation and lineage
- `examples/benchmark_config.json` shows an illustrative benchmark layout

## Project Notes

- `dsl-core/` is treated as an external, read-only reference for the fixed `L1` DSL.
- The current library scope is deterministic preparation and schema-contract work; live LLM calls are intentionally out of scope here.
- Drift handling, patch application, and benchmark reporting are offline-only surfaces in the current repository.
- If you need commands for running the test suites, fixtures, or focused verification flows, use [tests/README.md](tests/README.md).
