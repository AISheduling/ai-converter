# MappingIR prompts

`TASK-03` adds a file-backed prompt layer under `prompts/` for the offline synthesis pipeline.

## Template layout

- `prompts/source_schema/v1-system.txt`
- `prompts/source_schema/v1-user.txt`
- `prompts/mapping_ir/v1-system.txt`
- `prompts/mapping_ir/v1-user.txt`
- `prompts/repair/v1-system.txt`
- `prompts/repair/v1-user.txt`

The `v1-*.txt` naming convention keeps templates versioned without coupling the loader to a runtime network dependency.

## Renderers

The renderers live in `src/llm_converter/llm/prompt_renderers.py` and build:

- a source-schema synthesis prompt from `ProfileReport`
- a mapping synthesis prompt from `SourceSchemaSpec + TargetSchemaCard`
- a bounded repair prompt from a failing fixture, expected/actual diff, and the current `MappingIR`

Each renderer returns a `PromptEnvelope` with:

- rendered `system_prompt`
- rendered `user_prompt`
- prompt family/version reference
- deterministic metadata for downstream tracing

## Offline testing

The fake adapter in `src/llm_converter/llm/fake_client.py` consumes queued `FakeLLMReply` objects and validates structured outputs locally against Pydantic models.

This lets `tests/unit/mapping_ir/` cover:

- prompt rendering
- structured output parsing
- candidate ranking
- repair context generation

without live network or LLM calls.
