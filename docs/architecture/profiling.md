## Profiling Flow

`TASK-01` introduces a deterministic profiling layer that turns raw `L0` schedule descriptions into one canonical `ProfileReport`.

The flow is:

1. `loaders.py` reads `CSV`, `JSON`, or `JSONL` and normalizes them into record dictionaries.
2. `csv_profiler.py` and `json_profiler.py` flatten each record into path-based observations such as `tasks[].id`.
3. `report_builder.py` aggregates field/path statistics, computes representative samples, and builds the final `ProfileReport`.
4. `fingerprint.py` hashes stable structural attributes so later tasks can detect format drift without depending on row ordering.

The report is designed to be the handoff artifact for later schema induction and mapping tasks. `dsl-core` remains an external L1 reference only and is not part of the profiling runtime.

## Minimal usage

Run the focused profiling suite with:

```bash
poetry run python -m pytest tests/unit/profiling -q -p no:cacheprovider
```

Build one report locally with:

```python
from llm_converter.profiling import build_profile_report

report = build_profile_report("tests/fixtures/profiling/projects.json")

print(report.metadata.source_format)
print(report.record_count)
print(report.field_profiles[0].path)
```
