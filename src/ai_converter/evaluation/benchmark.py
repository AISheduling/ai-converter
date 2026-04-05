"""Benchmark harness for reproducible offline converter evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.validation import AcceptanceCase, AcceptanceCaseReport, AcceptanceReport, SemanticAssertion, run_acceptance_suite

from .metrics import BenchmarkMetrics, CaseAccuracyMetrics, build_benchmark_metrics, compute_case_accuracy


@dataclass(slots=True)
class BenchmarkCase:
    """One benchmark fixture case executed against a converter."""

    name: str
    record: dict[str, Any]
    expected_output: dict[str, Any]
    required_fields: list[str] = field(default_factory=list)
    assertions: list[SemanticAssertion] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkScenario:
    """Named collection of benchmark cases for one target surface."""

    name: str
    cases: list[BenchmarkCase]
    target_model: type[BaseModel] | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkSubject:
    """Converter under test plus the preparation callable used by the harness."""

    name: str
    prepare: Callable[[], Callable[[dict[str, Any]], dict[str, Any]]]
    kind: Literal["baseline", "compiled", "drift", "repair"] = "baseline"

    @classmethod
    def from_converter(
        cls,
        name: str,
        converter: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        kind: Literal["baseline", "compiled", "drift", "repair"] = "baseline",
    ) -> "BenchmarkSubject":
        """Build a benchmark subject from an already-prepared converter.

        Args:
            name: Stable subject name used in reports.
            converter: Callable converter entry point.
            kind: Subject category used by reporting.

        Returns:
            A benchmark subject that reuses the provided converter.
        """

        return cls(name=name, prepare=lambda: converter, kind=kind)


class BenchmarkCaseResult(BaseModel):
    """Per-case benchmark result for one subject/scenario pair."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tags: list[str] = Field(default_factory=list)
    execution_success: bool
    runtime_seconds: float = Field(ge=0.0, exclude=True)
    output: dict[str, Any] | None = None
    error: str | None = None
    metrics: CaseAccuracyMetrics
    structural_validity: bool | None = None
    semantic_validity: bool | None = None


class BenchmarkSubjectResult(BaseModel):
    """Benchmark result for one subject within one scenario."""

    model_config = ConfigDict(extra="forbid")

    subject_name: str
    subject_kind: str
    preparation_seconds: float = Field(ge=0.0, exclude=True)
    case_results: list[BenchmarkCaseResult] = Field(default_factory=list)
    metrics: BenchmarkMetrics
    acceptance_report: AcceptanceReport | None = None


class BenchmarkScenarioResult(BaseModel):
    """Benchmark results for all subjects in one scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_name: str
    tags: list[str] = Field(default_factory=list)
    subject_results: list[BenchmarkSubjectResult] = Field(default_factory=list)


class BenchmarkRunResult(BaseModel):
    """Top-level benchmark result across all configured scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenario_results: list[BenchmarkScenarioResult] = Field(default_factory=list)


def run_benchmark(
    subjects: list[BenchmarkSubject],
    scenarios: list[BenchmarkScenario],
) -> BenchmarkRunResult:
    """Execute benchmark scenarios for multiple converter subjects.

    Args:
        subjects: Converter subjects under test.
        scenarios: Benchmark scenarios to execute.

    Returns:
        Machine-readable benchmark run results.
    """

    scenario_results: list[BenchmarkScenarioResult] = []
    for scenario in scenarios:
        subject_results = [
            _run_subject_on_scenario(subject, scenario)
            for subject in subjects
        ]
        scenario_results.append(
            BenchmarkScenarioResult(
                scenario_name=scenario.name,
                tags=list(scenario.tags),
                subject_results=subject_results,
            )
        )
    return BenchmarkRunResult(scenario_results=scenario_results)


def _run_subject_on_scenario(
    subject: BenchmarkSubject,
    scenario: BenchmarkScenario,
) -> BenchmarkSubjectResult:
    """Run one benchmark subject across a single benchmark scenario.

    Args:
        subject: Converter subject under test.
        scenario: Scenario to execute.

    Returns:
        Benchmark subject result for the scenario.
    """

    preparation_started = perf_counter()
    converter = subject.prepare()
    preparation_seconds = perf_counter() - preparation_started

    case_results: list[BenchmarkCaseResult] = []
    runtime_seconds = 0.0
    execution_success = True

    for case in scenario.cases:
        case_started = perf_counter()
        try:
            output = converter(case.record)
            if not isinstance(output, dict):
                raise TypeError("benchmark converter must return a dictionary payload")
            error = None
        except Exception as exc:
            output = None
            error = str(exc)
            execution_success = False

        case_runtime = perf_counter() - case_started
        runtime_seconds += case_runtime
        case_metrics = compute_case_accuracy(
            case.expected_output,
            output,
            required_fields=case.required_fields,
        )
        case_results.append(
            BenchmarkCaseResult(
                name=case.name,
                tags=list(case.tags),
                execution_success=error is None,
                runtime_seconds=case_runtime,
                output=output,
                error=error,
                metrics=case_metrics,
            )
        )

    acceptance_report = _build_acceptance_report(converter, scenario)
    if acceptance_report is not None:
        case_reports_by_name = {
            report.name: report for report in acceptance_report.cases
        }
        case_results = [
            _attach_acceptance_result(case_result, case_reports_by_name.get(case_result.name))
            for case_result in case_results
        ]

    metrics = build_benchmark_metrics(
        [case_result.metrics for case_result in case_results],
        preparation_seconds=preparation_seconds,
        runtime_seconds=runtime_seconds,
        execution_success=execution_success,
        acceptance_report=acceptance_report,
    )
    return BenchmarkSubjectResult(
        subject_name=subject.name,
        subject_kind=subject.kind,
        preparation_seconds=preparation_seconds,
        case_results=case_results,
        metrics=metrics,
        acceptance_report=acceptance_report,
    )


def _build_acceptance_report(
    converter: Callable[[dict[str, Any]], dict[str, Any]],
    scenario: BenchmarkScenario,
) -> AcceptanceReport | None:
    """Reuse the validation acceptance workflow when a target model exists.

    Args:
        converter: Prepared converter callable.
        scenario: Benchmark scenario to evaluate.

    Returns:
        Acceptance report when the scenario exposes a target model, otherwise
        ``None``.
    """

    if scenario.target_model is None:
        return None
    dataset = [
        AcceptanceCase(
            name=case.name,
            record=case.record,
            assertions=list(case.assertions),
        )
        for case in scenario.cases
    ]
    return run_acceptance_suite(converter, dataset, scenario.target_model)


def _attach_acceptance_result(
    case_result: BenchmarkCaseResult,
    acceptance_case: AcceptanceCaseReport | None,
) -> BenchmarkCaseResult:
    """Attach acceptance details to one benchmark case result.

    Args:
        case_result: Benchmark case result built from direct execution.
        acceptance_case: Optional acceptance report for the same case.

    Returns:
        Updated benchmark case result.
    """

    if acceptance_case is None:
        return case_result
    return case_result.model_copy(
        update={
            "structural_validity": acceptance_case.structural_validity,
            "semantic_validity": acceptance_case.semantic_validity,
        }
    )
