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
- Mapping IR code lives under `src/llm_converter/mapping_ir/`.
- Versioned prompt templates live under `prompts/source_schema/`, `prompts/mapping_ir/`, and `prompts/repair/`.
- Focused mapping-ir tests live under `tests/unit/mapping_ir/`.
- Preferred verification command for TASK-03 is `python -m pytest tests/unit/mapping_ir -q -p no:cacheprovider`.
- Use fake adapters in unit tests; do not call live models or the network.

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
- Do not modify `dsl-core/` while building `TargetSchemaCard`; use it only as the external L1 reference surface.
