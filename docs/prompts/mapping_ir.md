# MappingIR prompts

The offline synthesis pipeline uses a file-backed prompt layer under `prompts/`.

## Template layout

- `prompts/source_schema/v1-system.txt`
- `prompts/source_schema/v1-user.txt`
- `prompts/mapping_ir/v1-system.txt`
- `prompts/mapping_ir/v1-user.txt`
- `prompts/repair/v1-system.txt`
- `prompts/repair/v1-user.txt`

The `v1-*.txt` naming convention keeps templates versioned without coupling the loader to a runtime network dependency.

## Renderers

The renderers live in `src/ai_converter/llm/prompt_renderers.py` and build:

- a source-schema synthesis prompt from `ProfileReport`
- a mapping synthesis prompt from `SourceSchemaSpec + TargetSchemaCard`
- a bounded repair prompt from a failing fixture, expected/actual diff, and the current `MappingIR`

Each renderer returns a `PromptEnvelope` with:

- rendered `system_prompt`
- rendered `user_prompt`
- prompt family/version reference
- deterministic metadata for downstream tracing

Prompt family selection is explicit: `render_source_schema_prompt(...)` loads `prompts/source_schema/<version>-*.txt`, `render_mapping_ir_prompt(...)` loads `prompts/mapping_ir/<version>-*.txt`, and `render_repair_prompt(...)` loads `prompts/repair/<version>-*.txt`.

## Observability artifacts

`LLMResponse.to_trace_artifact()` exposes a stable JSON-compatible payload for offline persistence of:

- the rendered prompt inputs
- prompt template family/version references
- raw model reply text
- parsed structured payload when present
- usage metadata
- structured errors and deterministic request metadata

## Minimal usage

```python
from pydantic import BaseModel

from ai_converter.llm.prompt_renderers import render_mapping_ir_prompt
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec, build_target_schema_card


class DemoTask(BaseModel):
    id: str


source_schema = SourceSchemaSpec(
    source_name="demo",
    source_format="json",
    root_type="list",
    fields=[SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str")],
)
target_schema = build_target_schema_card(DemoTask)

prompt = render_mapping_ir_prompt(source_schema, target_schema, version="v1")

print(prompt.reference.family)
print(prompt.reference.version)
print(prompt.user_prompt[:120])
```

## Offline testing

The fake adapter in `src/ai_converter/llm/fake_client.py` consumes queued `FakeLLMReply` objects and validates structured outputs locally against Pydantic models.

This lets `tests/unit/mapping_ir/` cover:

- prompt rendering
- structured output parsing
- candidate ranking
- repair context generation

without live network or LLM calls.
