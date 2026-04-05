"""Public exports for deterministic benchmark metrics and reporting."""

from .benchmark import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkRunResult,
    BenchmarkScenario,
    BenchmarkScenarioResult,
    BenchmarkSubject,
    BenchmarkSubjectResult,
    run_benchmark,
)
from .metrics import (
    BenchmarkMetrics,
    CaseAccuracyMetrics,
    build_benchmark_metrics,
    compute_case_accuracy,
    compute_macro_micro_accuracy,
    compute_required_field_accuracy,
)
from .reporting import (
    export_benchmark_reports,
    render_benchmark_markdown,
    write_benchmark_csv,
    write_benchmark_json,
    write_benchmark_markdown,
    write_benchmark_telemetry_json,
)

__all__ = [
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkMetrics",
    "BenchmarkRunResult",
    "BenchmarkScenario",
    "BenchmarkScenarioResult",
    "BenchmarkSubject",
    "BenchmarkSubjectResult",
    "CaseAccuracyMetrics",
    "build_benchmark_metrics",
    "compute_case_accuracy",
    "compute_macro_micro_accuracy",
    "compute_required_field_accuracy",
    "export_benchmark_reports",
    "render_benchmark_markdown",
    "run_benchmark",
    "write_benchmark_csv",
    "write_benchmark_json",
    "write_benchmark_markdown",
    "write_benchmark_telemetry_json",
]
