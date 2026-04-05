## Benchmark Protocol

`TASK-05` adds a deterministic benchmark layer under `src/llm_converter/evaluation/`.

The benchmark harness is intentionally library-first. It does not require a CLI or any network access.

## Why this exists

Use acceptance tests when you need a pass/fail verdict for one compiled converter against a bounded fixture set. Use benchmarks when you need comparative metrics across multiple subjects, scenarios, or patch strategies and want JSON, CSV, and Markdown report artifacts you can inspect or archive.

### Inputs

- `BenchmarkSubject`
  - wraps a baseline, compiled, drift-patched, or repair-loop converter
  - prepares the callable once so preparation cost can be measured separately from runtime cost
- `BenchmarkScenario`
  - groups deterministic `BenchmarkCase` fixtures
  - may optionally attach a target `Pydantic` model so the harness can reuse `run_acceptance_suite(...)`
- `BenchmarkCase`
  - carries the source record, expected target output, required target paths, and optional semantic assertions

### Metrics

The harness computes:

- required-field accuracy
- macro field accuracy
- micro field accuracy
- `pass@1`
- coverage
- repair iterations
- preparation seconds
- runtime seconds

The metric helpers live in `src/llm_converter/evaluation/metrics.py`.

### Outputs

Use `export_benchmark_reports(...)` to write:

- JSON for machine-readable result ingestion
- CSV for flattened per-case comparisons
- Markdown for quick scenario and baseline review

The helper returns the concrete output paths, and the exported files are typically written into a repo-local directory such as `benchmark_artifacts/`.

### Minimal Workflow

```python
from pathlib import Path

from llm_converter.evaluation import (
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
export_benchmark_reports(result, Path("benchmark_artifacts"), stem="task05_demo")
```

### Fixture Guidance

- Keep benchmark and drift fixtures deterministic.
- Prefer synthetic scenarios under `tests/fixtures/drift/` over external datasets.
- Reuse fake or compiled converters only. Do not call live LLMs or the network from benchmark tests.

### Example Config

See `examples/benchmark_config.json` for an illustrative scenario layout you can adapt in a small local runner.
