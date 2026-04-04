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

## TASK-01 Notes

- Profiling code lives under `src/llm_converter/profiling/`.
- Profiling fixtures live under `tests/fixtures/profiling/`.
- Focused profiling tests live under `tests/unit/profiling/`.
- Preferred verification command for TASK-01 is `python -m pytest tests/unit/profiling -q -p no:cacheprovider`.
- Treat `dsl-core/` as an external L1 reference library during TASK-01; do not modify it while changing the profiling layer.

## TASK-03 Notes

- LLM adapter code lives under `src/llm_converter/llm/`.
- Concrete OpenAI adapter lives in `src/llm_converter/llm/openai_adapter.py`.
- Mapping IR code lives under `src/llm_converter/mapping_ir/`.
- Versioned prompt templates live under `prompts/source_schema/`, `prompts/mapping_ir/`, and `prompts/repair/`.
- Focused mapping-ir tests live under `tests/unit/mapping_ir/`.
- Preferred verification command for TASK-03 is `python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider`.
- Use fake or injected adapters in unit tests; do not call live models or the network.

## TASK-04 Notes

- Compiler code lives under `src/llm_converter/compiler/`.
- Validation and acceptance code lives under `src/llm_converter/validation/`.
- Focused compiler tests live under `tests/unit/compiler/`.
- Focused validation tests live under `tests/unit/validation/`.
- Smoke integration tests live under `tests/integration/converter_pipeline/`.
- Preferred verification command for TASK-04 is `python -m pytest tests/unit/mapping_ir tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider`.
- Keep runtime compilation and repair-loop tests offline; use fake repair strategies and avoid live LLM calls or network access.

## TASK-05 Notes

- Drift detection code lives under `src/llm_converter/drift/`.
- Benchmark and reporting code lives under `src/llm_converter/evaluation/`.
- Drift fixtures live under `tests/fixtures/drift/`.
- Focused TASK-05 tests live under `tests/unit/drift/` and `tests/unit/evaluation/`.
- Benchmark protocol docs live under `docs/evaluation/benchmark_protocol.md`.
- Example benchmark configs live under `examples/`.
- Preferred verification command for TASK-05 is `python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider`.
- Keep drift heuristics, patch application, and benchmark/reporting tests offline; use fake or deterministic converters and do not call live models or the network.

## Project Notes

- `TASK-01` creates the initial profiling layer under `src/llm_converter/profiling/`.
- Keep `dsl-core/` read-only for now; it is treated as an external reference library and example corpus.
- Focused profiling fixtures live in `tests/fixtures/profiling/`.
- Focused profiling tests run with `pytest tests/unit/profiling -q`.
- `TASK-02` adds schema contracts under `src/llm_converter/schema/`.
- Schema fixtures live under `tests/fixtures/schema/`.
- Focused schema tests run with `python -m pytest tests/unit/schema -q -p no:cacheprovider`.
- `TASK-03` adds the offline LLM adapter layer and MappingIR contracts under `src/llm_converter/llm/` and `src/llm_converter/mapping_ir/`.
- Prompt templates for `TASK-03` live under `prompts/`.
- Focused mapping-ir tests run with `python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider`.
- `TASK-04` adds deterministic execution under `src/llm_converter/compiler/` and acceptance validation under `src/llm_converter/validation/`.
- Focused TASK-04 tests run with `python -m pytest tests/unit/compiler tests/unit/validation tests/integration/converter_pipeline -q -p no:cacheprovider`.
- `TASK-05` adds deterministic drift detection and benchmark evaluation under `src/llm_converter/drift/` and `src/llm_converter/evaluation/`.
- Focused TASK-05 tests run with `python -m pytest tests/unit/drift tests/unit/evaluation -q -p no:cacheprovider`.
- Benchmark examples live under `examples/`, and benchmark protocol docs live under `docs/evaluation/`.
- `tests/integration/converter_pipeline/` may reuse deterministic profiling fixtures or local inline models, but must stay offline and must not modify `dsl-core/`.
- Do not modify `dsl-core/` while building `TargetSchemaCard`; use it only as the external L1 reference surface.
