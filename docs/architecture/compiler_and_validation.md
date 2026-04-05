# Compiler And Validation

`TASK-04` adds the deterministic execution layer that turns a validated `MappingIR` program into a versioned `ConverterPackage` artifact and then validates the produced payload offline.

## Flow

1. `src/llm_converter/mapping_ir/validator.py` checks that a candidate program is structurally safe to execute.
2. `src/llm_converter/compiler/compiler.py` normalizes step order, emits deterministic Python source, loads an importable module, and wraps it in a versioned `ConverterPackage`.
3. `src/llm_converter/compiler/runtime_ops.py` provides the pure helpers used by generated modules.
4. `src/llm_converter/validation/structural.py` validates converter output against a target `Pydantic` model.
5. `src/llm_converter/validation/semantic.py` applies deterministic semantic assertions on top of the structural result.
6. `src/llm_converter/validation/acceptance.py` runs dataset-level acceptance and computes unified status fields.
7. `src/llm_converter/validation/repair_loop.py` provides the bounded offline repair orchestration used by tests and future adapters.

## Compiler Design

- Compilation is deterministic for the same `MappingIR` input.
- Steps are topologically ordered with stable tie-breaking by original order.
- The package manifest records the converter entry point, validation entry points, focused test surface, and a stable source digest.
- Generated modules expose a record-level `convert(record)` callable.
- Generated code imports only the local runtime helper module and never reaches out to a live LLM client.

## ConverterPackage Contract

The compiler boundary now returns an explicit `ConverterPackage` artifact instead of an unstructured in-memory result.

The package keeps the existing runtime surface:

- `program`
- `module_name`
- `source_code`
- `module`
- `convert(record)`

In addition, it exposes:

- a versioned machine-readable `manifest`
- `to_manifest_payload()` for JSON-compatible metadata
- `export(path)` for deterministic repo-local export of:
  - `manifest.json`
  - `<module_name>.py`
  - `mapping_ir.json`

## Runtime Helpers

The runtime layer currently covers the operation surface required by `TASK-04`:

- `copy` and `rename`
- `cast`
- `map_enum`
- `unit_convert`
- `split`
- `merge`
- `nest`
- `unnest`
- `default`
- `derive`
- `validate`
- `drop`

`derive` and `validate` use a restricted AST evaluator instead of free `eval`.

## Validation Layers

Structural validation returns machine-readable issues with field paths and error codes derived from `Pydantic`.

Semantic validation is intentionally separate so a payload can be structurally valid but semantically wrong, for example:

- wrong field copied into a required target field
- incorrect enum translation
- incorrect unit scaling
- failed derived-field predicate

## Acceptance And Repair

The acceptance suite runs a compiled converter over a deterministic dataset and reports:

- `execution_success`
- `structural_validity`
- `semantic_validity`
- `coverage`
- `repair_iterations`

The repair loop wraps that report in a failure bundle, asks a repair strategy for a patched `MappingIR`, recompiles, and reruns acceptance until the maximum repair count is reached.

In `TASK-04`, repair strategies are fake or stubbed in tests; live LLM repair is intentionally out of scope.

## Minimal usage

Run the focused compiler and validation checks with:

```bash
poetry run python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider
```

Compile one mapping and validate the output with:

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
result = validate_structural_output(package.convert({"task_id": "T-1"}), DemoTarget)

print(result.valid)
print(package.manifest.artifact_kind)
```
