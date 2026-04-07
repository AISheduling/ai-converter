# Synthetic Template Generators

`TASK-Bench-03` adds an offline-testable LLM-assisted generator layer under
`src/ai_converter/synthetic_benchmark/generators/llm/`.

Its job is intentionally narrow:

- render a file-backed prompt for synthetic template generation
- request a structured `TemplateGenerationCandidate` through the shared
  `ai_converter.llm.LLMAdapter`
- validate the candidate through parse, policy, dry-run, serialization, and
  diversity gates
- cache accepted templates with deterministic metadata and optional LLM trace
  artifacts
- stop after a bounded number of attempts without blocking the wider workflow

The active prompt-bundle source of truth for this FR-2 surface is
`prompts/synthetic_benchmark_template/`.

It does not generate canonical scenarios, does not generate gold `L1`, and does
not call live models in unit tests.

## Package Layout

- `models.py`: typed request, candidate, validation, cache, patch, and result
  contracts
- `prompt_builder.py`: file-backed prompt rendering via the shared `prompts/`
  layout
- `validator.py`: parse, policy, dry-run, serialization, and diversity gates
- `cache.py`: deterministic prompt hashing, cache-key derivation, and JSON
  persistence
- `generator.py`: bounded orchestration over `LLMAdapter` through
  `SyntheticTemplateLLMGenerator`

Main public entry points:

- `SyntheticTemplateLLMGenerator`
- `TemplateGenerationRequest`
- `TemplateGenerationCandidate`
- `AcceptedTemplateCache`
- `AcceptedTemplateCacheEntry`
- `TemplateGenerationResult`

## Validation Gates

Each template candidate must pass these gates before it can be accepted:

1. structured parse into the expected response schema
2. policy validation for blank keys and duplicate required aliases
3. dry-run rendering against a deterministic `CanonicalScenario`
4. deterministic `BundleStore` save/load roundtrip checks
5. diversity checks against already accepted templates

If any gate fails, the generator records the machine-readable report for that
attempt and retries only until `max_attempts` is exhausted.

## Cache Semantics

Accepted templates are cached as `AcceptedTemplateCacheEntry` JSON payloads
containing at least:

- `cache_key`
- `prompt_hash`
- `llm_model_config`
- `accepted_template`
- `validation_report`
- optional `response_trace`

`TemplateGenerationResult.status` reports whether a run was `accepted`,
`cache_hit`, or `rejected`. When the same prompt hash, `llm_model_config`
payload, and cache namespace are reused, the generator can return the cached
accepted template without calling the adapter again.

## Verification

Focused command:

```bash
python -m pytest tests/unit/synthetic_benchmark/generators_llm -q -p no:cacheprovider
```

Recommended regressions when shared exports or prompts are touched:

```bash
python -m pytest tests/unit/synthetic_benchmark tests/unit/mapping_ir -q -p no:cacheprovider
```
