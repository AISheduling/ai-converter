## Benchmark Protocol

The deterministic benchmark layer lives under `src/ai_converter/evaluation/`.

The benchmark harness is intentionally library-first. It does not require a CLI
or any network access.

## Why this exists

Use acceptance tests when you need a pass/fail verdict for one compiled
converter against a bounded fixture set. Use benchmarks when you need
comparative metrics across multiple subjects, scenarios, or repeated runs and
want canonical JSON, CSV, Markdown, and optional telemetry artifacts that you
can inspect or archive offline.

## Inputs

- `BenchmarkSubject`
  - wraps a baseline, compiled, drift-patched, or repair-loop converter
  - prepares the callable once so preparation cost can be measured separately
    from runtime cost
  - can optionally expose stage-wise signals through
    `BenchmarkStageArtifacts`
- `BenchmarkScenario`
  - groups deterministic `BenchmarkCase` fixtures
  - may optionally attach a target `Pydantic` model so the harness can reuse
    `run_acceptance_suite(...)`
- `BenchmarkCase`
  - carries the source record, expected target output, required target paths,
    optional semantic assertions, and stable grouping tags

### Synthetic benchmark adapters

Synthetic benchmark tasks should reuse the existing harness rather than define a
second stack:

- use `build_synthetic_benchmark_case(...)` to adapt one `DatasetBundle` into a
  benchmark case
- use `build_synthetic_benchmark_scenario(...)` to adapt base or drift bundles
  into a normal `BenchmarkScenario`
- use `BenchmarkSubject.from_converter_package(...)` when you already have a
  compiled `ConverterPackage`

Synthetic scenario tags stay machine-readable and deterministic. The helpers
emit tags such as:

- `synthetic`
- `base` or `drift`
- `severity:<level>`
- `compatibility:<class>`
- `dataset:<dataset_id>`
- `template:<template_id>`

## Metrics

The harness computes the existing end-to-end metrics:

- required-field accuracy
- macro field accuracy
- micro field accuracy
- `pass@1`
- coverage
- repair iterations
- preparation seconds
- runtime seconds

Wall-clock timing remains telemetry, not part of the canonical machine-readable
benchmark contract.

When intermediate stage data is available, `BenchmarkMetrics.stage_metrics`
captures optional stage-wise signals such as:

- build/prepare success
- execution success rate
- runtime validity rate
- structural validity rate
- semantic validity rate
- optional upstream scores such as source-structure recovery or mapping quality

The metric helpers live in `src/ai_converter/evaluation/metrics.py`.

## Repeated runs

Use `run_repeated_benchmark(...)` when you want `N` independent benchmark
passes without introducing a second harness API. Each run remains a normal
`BenchmarkRunResult`, and the repeated-run container keeps deterministic `run_id`
values such as `run-001`, `run-002`, and so on.

`TASK-Bench-04` stops at grouped artifact layout and repeated-run capture. Cross
run aggregation, grouped summaries, and boxplot-ready rollups belong to
`TASK-Bench-05`.

Use `summarize_benchmark_experiment(...)` when you need grouped repeated-run
statistics without introducing a second reporting layer. The grouped summary
surface computes:

- `mean`, `median`, `std`, `min`, `max`
- quartiles and `IQR`
- base-vs-drift rollups
- drift-type, severity, and compatibility-class rollups
- stage-metric aggregates when `BenchmarkMetrics.stage_metrics` is present

Use `summarize_benchmark_telemetry(...)` only for timing summaries. Timing
distributions stay sidecar-only and are never reconstructed from canonical
benchmark JSON or CSV exports.

## Outputs

Use `export_benchmark_reports(...)` to write one benchmark run into:

- canonical JSON for machine-readable result ingestion
- canonical CSV for flattened per-case comparisons
- Markdown for quick scenario and baseline review
- optional telemetry JSON sidecar when timing diagnostics are needed

Use `export_benchmark_experiment_reports(...)` to write repeated runs into a
deterministic grouped layout:

```text
benchmark_artifacts/
├─ benchmark.experiment.json
├─ benchmark.experiment.md
└─ runs/
   ├─ run-001/
   │  ├─ benchmark.json
   │  ├─ benchmark.csv
   │  ├─ benchmark.md
   │  └─ benchmark.telemetry.json
   └─ run-002/
      ├─ benchmark.json
      ├─ benchmark.csv
      ├─ benchmark.md
      └─ benchmark.telemetry.json
```

The experiment manifest records run ids, scenario names, scenario tags, and the
relative artifact paths written for each run. Canonical `benchmark.json` and
`benchmark.csv` intentionally omit volatile wall-clock timing fields so repeated
deterministic runs can produce stable machine-readable artifacts. Timing
diagnostics remain in the optional telemetry sidecars.

Grouped experiment exports also write:

- `benchmark.summary.json` and `benchmark.summary.csv` for repeated-run summary
  statistics
- `benchmark.boxplot.csv` for long-form canonical boxplot-ready rows
- `benchmark.telemetry.summary.json` and `benchmark.telemetry.summary.csv` for
  timing-only grouped summaries
- `benchmark.telemetry.boxplot.csv` for long-form timing distributions derived
  strictly from telemetry sidecars

`benchmark.boxplot.csv` is the canonical repeated-run distribution export. It
contains one row per run, scenario, subject, and metric with machine-readable
grouping columns such as `bundle_kind`, `drift_type`, `severity`, and
`compatibility_class`.

Use `benchmark.telemetry.boxplot.csv` for timing boxplots instead of mining
timing fields back out of canonical artifacts.

## Minimal workflow

### Single run

```python
from pathlib import Path

from ai_converter.evaluation import (
    BenchmarkSubject,
    build_synthetic_benchmark_scenario,
    export_benchmark_reports,
    run_benchmark,
)

subject = BenchmarkSubject.from_converter(
    "synthetic-compiled",
    convert_synthetic_payload,
    kind="compiled",
)
scenario = build_synthetic_benchmark_scenario(
    "synthetic-base",
    [base_bundle],
    target_model=SyntheticTarget,
    required_fields=["tasks"],
)

result = run_benchmark([subject], [scenario])
export_benchmark_reports(result, Path("benchmark_artifacts"), stem="synthetic_base")
```

### Repeated run

```python
from pathlib import Path

from ai_converter.evaluation import (
    export_benchmark_experiment_reports,
    run_repeated_benchmark,
)

experiment = run_repeated_benchmark(
    [subject],
    [scenario],
    run_count=3,
    experiment_name="synthetic-demo",
)
export_benchmark_experiment_reports(
    experiment,
    Path("benchmark_artifacts"),
    stem="synthetic_benchmark",
    include_telemetry=True,
)
```

The export above writes:

- per-run canonical reports under `runs/<run_id>/`
- grouped repeated-run summaries in `synthetic_benchmark.summary.json` and
  `synthetic_benchmark.summary.csv`
- boxplot-ready canonical rows in `synthetic_benchmark.boxplot.csv`
- telemetry-only grouped timing summaries in
  `synthetic_benchmark.telemetry.summary.json`,
  `synthetic_benchmark.telemetry.summary.csv`, and
  `synthetic_benchmark.telemetry.boxplot.csv`

If you want a thin runnable wrapper over the same API, see
`examples/synthetic_benchmark/run_example.py`. It stays offline and delegates to
the library surface rather than introducing a second benchmark stack.

## Fixture guidance

- Keep benchmark and drift fixtures deterministic.
- Prefer synthetic bundles and drift specs under
  `tests/fixtures/synthetic_benchmark/` when they fit the scenario.
- Reuse fake or compiled converters only. Do not call live LLMs or the network
  from benchmark tests.

## Example config

See `examples/benchmark_config.json` for an illustrative synthetic benchmark
layout you can adapt in a small local runner.

For one ready-to-run offline workflow, use
`examples/synthetic_benchmark/run_example.py`. It creates a small deterministic
base/drift experiment, executes repeated runs through the same public library
API described above, and writes grouped summary plus telemetry artifacts under
`examples/synthetic_benchmark/generated/`.
