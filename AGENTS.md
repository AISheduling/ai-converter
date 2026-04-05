<!-- repo-task-proof-loop:start -->
## Repo task proof loop

For substantial features, refactors, and bug fixes, use the repo-task-proof-loop workflow.

Required artifact path:
- Keep all task artifacts in `.agent/tasks/<TASK_ID>/` inside this repository.

Required sequence:
1. Freeze `.agent/tasks/<TASK_ID>/spec.md` before implementation.
2. Implement against explicit acceptance criteria (`AC1`, `AC2`, ...).
3. Create `evidence.md`, `evidence.json`, and raw artifacts.
4. Run a fresh verification pass against the current codebase and rerun checks.
5. If verification is not `PASS`, write `problems.md`, apply the smallest safe fix, and reverify.

Hard rules:
- Do not claim completion unless every acceptance criterion is `PASS`.
- Verifiers judge current code and current command results, not prior chat claims.
- Fixers should make the smallest defensible diff.
- For broad Codex tasks, bounded fan-out is allowed only after `init`, only when the user has explicitly asked for delegation or parallel agent work, and only when task shape warrants it: use bounded `explorer` children before or after spec freeze, use bounded `worker` children only after the spec is frozen, keep the task tree shallow, keep evidence ownership with one builder, and keep verdict ownership with one fresh verifier.
- This root `AGENTS.md` block is the repo-wide Codex baseline. More-specific nested `AGENTS.override.md` or `AGENTS.md` files still take precedence for their directory trees.
- Keep this block lean. If the workflow needs more Codex guidance, prefer nested `AGENTS.md` / `AGENTS.override.md` files or configured fallback guide docs instead of expanding this root block indefinitely.

Installed workflow agents:
- `.codex/agents/task-spec-freezer.toml`
- `.codex/agents/task-builder.toml`
- `.codex/agents/task-verifier.toml`
- `.codex/agents/task-fixer.toml`
<!-- repo-task-proof-loop:end -->

## Profiling Notes

- Profiling code lives under `src/llm_converter/profiling/`.
- Profiling fixtures live under `tests/fixtures/profiling/`.
- Focused profiling tests live under `tests/unit/profiling/`.
- Preferred profiling verification command is `python -m pytest tests/unit/profiling -q -p no:cacheprovider`.
- Treat `dsl-core/` as an external L1 reference library during profiling work; do not modify it while changing the profiling layer.

## LLM Adapter And Mapping IR Notes

- LLM adapter code lives under `src/ai_converter/llm/`.
- Concrete OpenAI adapter lives in `src/ai_converter/llm/openai_adapter.py`.
- Mapping IR code lives under `src/ai_converter/mapping_ir/`.
- Versioned prompt templates live under `prompts/source_schema/`, `prompts/mapping_ir/`, and `prompts/repair/`.
- Focused mapping-ir tests live under `tests/unit/mapping_ir/`.
- Preferred mapping-ir verification command is `python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider`.
- Use fake or injected adapters in unit tests; do not call live models or the network.
- Prompt/model trace artifacts are caller-managed exports from the shared `LLMResponse.to_trace_artifact()` contract; tests must keep them offline and deterministic.

## Compiler And Validation Notes

- Compiler code lives under `src/ai_converter/compiler/`.
- Validation and acceptance code lives under `src/ai_converter/validation/`.
- `compile_mapping_ir()` now returns a versioned `ConverterPackage` artifact that preserves `.convert(...)` while exposing deterministic manifest/export semantics for compiler outputs.
- Focused compiler tests live under `tests/unit/compiler/`.
- Focused validation tests live under `tests/unit/validation/`.
- Smoke integration tests live under `tests/integration/converter_pipeline/`.
- Preferred compiler/validation verification command is `python -m pytest tests/unit/mapping_ir tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider`.
- Keep runtime compilation and repair-loop tests offline; use fake repair strategies and avoid live LLM calls or network access.
- Acceptance reports stay JSON-exportable through `AcceptanceReport.to_trace_artifact()`, and repair-loop audit exports now include per-attempt traces plus a final decision through `RepairLoopResult.to_trace_artifact()`.

## Drift And Evaluation Notes

- Drift detection code lives under `src/llm_converter/drift/`.
- Benchmark and reporting code lives under `src/llm_converter/evaluation/`.
- Drift fixtures live under `tests/fixtures/drift/`.
- Focused drift and evaluation tests live under `tests/unit/drift/` and `tests/unit/evaluation/`.
- Benchmark protocol docs live under `docs/evaluation/benchmark_protocol.md`.
- Example benchmark configs live under `examples/`.
- Preferred drift/evaluation verification command is `python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider`.
- Keep drift heuristics, patch application, and benchmark/reporting tests offline; use fake or deterministic converters and do not call live models or the network.

## Project Notes

- The profiling layer lives under `src/llm_converter/profiling/`.
- Keep `dsl-core/` read-only for now; it is treated as an external reference library and example corpus.
- Focused profiling fixtures live in `tests/fixtures/profiling/`.
- Focused profiling tests run with `pytest tests/unit/profiling -q`.
- Schema contracts live under `src/llm_converter/schema/`.
- Schema fixtures live under `tests/fixtures/schema/`.
- Focused schema tests run with `python -m pytest tests/unit/schema -q -p no:cacheprovider`.
- The offline LLM adapter layer and MappingIR contracts live under `src/llm_converter/llm/` and `src/llm_converter/mapping_ir/`.
- Prompt templates for the mapping pipeline live under `prompts/`.
- Focused mapping-ir tests run with `python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider`.
- Deterministic execution and acceptance validation live under `src/llm_converter/compiler/` and `src/llm_converter/validation/`.
- Focused compiler/validation tests run with `python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider`.
- Deterministic drift detection and benchmark evaluation live under `src/llm_converter/drift/` and `src/llm_converter/evaluation/`.
- Focused drift/evaluation tests run with `python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider`.
- Benchmark examples live under `examples/`, and benchmark protocol docs live under `docs/evaluation/`.
- `tests/integration/converter_pipeline/` may reuse deterministic profiling fixtures or local inline models, but must stay offline and must not modify `dsl-core/`.
- Do not modify `dsl-core/` while building `TargetSchemaCard`; use it only as the external L1 reference surface.
