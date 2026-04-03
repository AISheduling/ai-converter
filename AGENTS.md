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

## Project Notes

- `TASK-01` creates the initial profiling layer under `src/llm_converter/profiling/`.
- Keep `dsl-core/` read-only for now; it is treated as an external reference library and example corpus.
- Focused profiling fixtures live in `tests/fixtures/profiling/`.
- Focused profiling tests run with `pytest tests/unit/profiling -q`.
- `TASK-02` adds schema contracts under `src/llm_converter/schema/`.
- Schema fixtures live under `tests/fixtures/schema/`.
- Focused schema tests run with `python -m pytest tests/unit/schema -q -p no:cacheprovider`.
- Do not modify `dsl-core/` while building `TargetSchemaCard`; use it only as the external L1 reference surface.
