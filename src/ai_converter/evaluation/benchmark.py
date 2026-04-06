"""Benchmark harness for reproducible offline converter evaluation."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.compiler import ConverterPackage
from ai_converter.synthetic_benchmark.storage.models import DatasetBundle
from ai_converter.validation import (
    AcceptanceCase,
    AcceptanceCaseReport,
    AcceptanceReport,
    SemanticAssertion,
    run_acceptance_suite,
)

from .metrics import (
    BenchmarkMetrics,
    BenchmarkStageArtifacts,
    CaseAccuracyMetrics,
    build_benchmark_metrics,
    build_stage_metrics,
    compute_case_accuracy,
)


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
    """Converter under test plus optional stage-level diagnostics."""

    name: str
    prepare: Callable[[], Callable[[dict[str, Any]], dict[str, Any]]]
    kind: Literal["baseline", "compiled", "drift", "repair"] = "baseline"
    stage_artifacts: BenchmarkStageArtifacts | None = None

    @classmethod
    def from_converter(
        cls,
        name: str,
        converter: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        kind: Literal["baseline", "compiled", "drift", "repair"] = "baseline",
        stage_artifacts: BenchmarkStageArtifacts | None = None,
    ) -> "BenchmarkSubject":
        """Build a benchmark subject from an already-prepared converter.

        Args:
            name: Stable subject name used in reports.
            converter: Callable converter entry point.
            kind: Subject category used by reporting.
            stage_artifacts: Optional stage-level subject diagnostics.

        Returns:
            A benchmark subject that reuses the provided converter.
        """

        return cls(
            name=name,
            prepare=lambda: converter,
            kind=kind,
            stage_artifacts=stage_artifacts,
        )

    @classmethod
    def from_converter_package(
        cls,
        name: str,
        package: ConverterPackage,
        *,
        kind: Literal["baseline", "compiled", "drift", "repair"] = "compiled",
        stage_artifacts: BenchmarkStageArtifacts | None = None,
    ) -> "BenchmarkSubject":
        """Build a benchmark subject from a compiled converter package.

        Args:
            name: Stable subject name used in reports.
            package: Compiled converter package under test.
            kind: Subject category used by reporting.
            stage_artifacts: Optional stage-level subject diagnostics.

        Returns:
            Benchmark subject that calls ``package.convert``.
        """

        return cls.from_converter(
            name,
            package.convert,
            kind=kind,
            stage_artifacts=stage_artifacts,
        )


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


class BenchmarkExperimentRun(BaseModel):
    """One repeated benchmark run captured inside an experiment result."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    result: BenchmarkRunResult


class BenchmarkExperimentResult(BaseModel):
    """Grouped repeated benchmark runs for one deterministic experiment."""

    model_config = ConfigDict(extra="forbid")

    experiment_name: str | None = None
    runs: list[BenchmarkExperimentRun] = Field(default_factory=list)


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


def run_repeated_benchmark(
    subjects: list[BenchmarkSubject],
    scenarios: list[BenchmarkScenario],
    *,
    run_count: int,
    run_id_prefix: str = "run",
    experiment_name: str | None = None,
) -> BenchmarkExperimentResult:
    """Execute the same benchmark configuration for ``N`` repeated runs.

    Args:
        subjects: Converter subjects under test.
        scenarios: Benchmark scenarios to execute.
        run_count: Number of repeated benchmark passes to execute.
        run_id_prefix: Stable run identifier prefix.
        experiment_name: Optional experiment label for grouped exports.

    Returns:
        Grouped repeated benchmark result.
    """

    if run_count < 1:
        raise ValueError("run_count must be at least 1")

    runs: list[BenchmarkExperimentRun] = []
    for index in range(run_count):
        run_id = f"{run_id_prefix}-{index + 1:03d}"
        runs.append(
            BenchmarkExperimentRun(
                run_id=run_id,
                result=run_benchmark(subjects, scenarios),
            )
        )
    return BenchmarkExperimentResult(experiment_name=experiment_name, runs=runs)


def build_synthetic_benchmark_case(
    bundle: DatasetBundle,
    *,
    name: str | None = None,
    required_fields: Sequence[str] = (),
    assertions: Sequence[SemanticAssertion] = (),
    tags: Sequence[str] = (),
) -> BenchmarkCase:
    """Build one benchmark case from a persisted synthetic bundle.

    Args:
        bundle: Synthetic base or drift bundle to adapt.
        name: Optional explicit case name. Defaults to the bundle id.
        required_fields: Optional required target paths for the case.
        assertions: Optional semantic assertions for the case.
        tags: Optional additional deterministic case tags.

    Returns:
        Benchmark case reusing the bundle's deterministic `L0` and `L1` payloads.

    Raises:
        TypeError: If the bundle `L0` payload is list-rooted instead of object-rooted.
    """

    if not isinstance(bundle.l0_payload, dict):
        raise TypeError(
            "synthetic benchmark adapters currently require object-root L0 payloads"
        )

    resolved_tags = _build_synthetic_case_tags(bundle)
    resolved_tags.extend(tags)
    return BenchmarkCase(
        name=name or bundle.metadata.bundle_id,
        record=copy.deepcopy(bundle.l0_payload),
        expected_output=copy.deepcopy(bundle.l1_payload),
        required_fields=list(required_fields),
        assertions=list(assertions),
        tags=_deduplicate_tags(resolved_tags),
    )


def build_synthetic_benchmark_scenario(
    name: str,
    bundles: Sequence[DatasetBundle],
    *,
    target_model: type[BaseModel] | None = None,
    required_fields: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> BenchmarkScenario:
    """Build one benchmark scenario from synthetic base or drift bundles.

    Args:
        name: Stable scenario name.
        bundles: Synthetic bundles to adapt into benchmark cases.
        target_model: Optional target model for acceptance validation reuse.
        required_fields: Optional required target paths copied onto each case.
        tags: Optional additional deterministic scenario tags.

    Returns:
        Benchmark scenario with one benchmark case per bundle.
    """

    cases = [
        build_synthetic_benchmark_case(
            bundle,
            required_fields=required_fields,
        )
        for bundle in bundles
    ]
    resolved_tags: list[str] = []
    for bundle in bundles:
        resolved_tags.extend(_build_synthetic_scenario_tags(bundle))
    resolved_tags.extend(tags)
    return BenchmarkScenario(
        name=name,
        cases=cases,
        target_model=target_model,
        tags=_deduplicate_tags(resolved_tags),
    )


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
    converter: Callable[[dict[str, Any]], dict[str, Any]] | None
    try:
        converter = subject.prepare()
        prepare_succeeded = True
        preparation_error = None
    except Exception as exc:
        converter = None
        prepare_succeeded = False
        preparation_error = str(exc)
    preparation_seconds = perf_counter() - preparation_started

    if converter is None:
        case_results = [
            _build_failed_case_result(
                case,
                preparation_error or "subject preparation failed",
            )
            for case in scenario.cases
        ]
        stage_metrics = build_stage_metrics(
            case_results,
            prepare_succeeded=False,
            stage_artifacts=subject.stage_artifacts,
        )
        metrics = build_benchmark_metrics(
            [case_result.metrics for case_result in case_results],
            preparation_seconds=preparation_seconds,
            runtime_seconds=0.0,
            execution_success=False,
            acceptance_report=None,
            stage_metrics=stage_metrics,
        )
        return BenchmarkSubjectResult(
            subject_name=subject.name,
            subject_kind=subject.kind,
            preparation_seconds=preparation_seconds,
            case_results=case_results,
            metrics=metrics,
            acceptance_report=None,
        )

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
            _attach_acceptance_result(
                case_result,
                case_reports_by_name.get(case_result.name),
            )
            for case_result in case_results
        ]

    stage_metrics = build_stage_metrics(
        case_results,
        prepare_succeeded=prepare_succeeded,
        stage_artifacts=subject.stage_artifacts,
        acceptance_report=acceptance_report,
    )
    metrics = build_benchmark_metrics(
        [case_result.metrics for case_result in case_results],
        preparation_seconds=preparation_seconds,
        runtime_seconds=runtime_seconds,
        execution_success=execution_success,
        acceptance_report=acceptance_report,
        stage_metrics=stage_metrics,
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


def _build_failed_case_result(
    case: BenchmarkCase,
    error: str,
) -> BenchmarkCaseResult:
    """Build one case result when subject preparation fails before execution.

    Args:
        case: Benchmark case that could not execute.
        error: Preparation error string.

    Returns:
        Failed benchmark case result.
    """

    return BenchmarkCaseResult(
        name=case.name,
        tags=list(case.tags),
        execution_success=False,
        runtime_seconds=0.0,
        output=None,
        error=error,
        metrics=compute_case_accuracy(
            case.expected_output,
            None,
            required_fields=case.required_fields,
        ),
        structural_validity=False,
        semantic_validity=False,
    )


def _build_synthetic_case_tags(bundle: DatasetBundle) -> list[str]:
    """Build deterministic synthetic-case tags for one benchmark case.

    Args:
        bundle: Synthetic bundle being adapted.

    Returns:
        Deterministic synthetic-case tags.
    """

    tags = _build_synthetic_scenario_tags(bundle)
    tags.append(f"bundle:{bundle.metadata.bundle_id}")
    return _deduplicate_tags(tags)


def _build_synthetic_scenario_tags(bundle: DatasetBundle) -> list[str]:
    """Build deterministic synthetic-scenario tags for one bundle.

    Args:
        bundle: Synthetic bundle being adapted.

    Returns:
        Deterministic scenario-level synthetic tags.
    """

    tags = [
        "synthetic",
        bundle.metadata.bundle_kind,
        f"dataset:{bundle.metadata.dataset_id}",
        f"template:{bundle.metadata.source_template_id}",
    ]
    if bundle.drift_manifest is not None:
        tags.extend(
            [
                "drift",
                f"drift_id:{bundle.drift_manifest.drift_id}",
                f"drift_type:{bundle.drift_manifest.drift_type}",
                f"severity:{bundle.drift_manifest.severity}",
                f"compatibility:{bundle.drift_manifest.compatibility_class}",
            ]
        )
    return _deduplicate_tags(tags)


def _deduplicate_tags(tags: Sequence[str]) -> list[str]:
    """Return deterministic tags while preserving first occurrence order.

    Args:
        tags: Candidate tag sequence.

    Returns:
        Deterministic tag list without duplicates or empty values.
    """

    seen: set[str] = set()
    deduplicated: list[str] = []
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        deduplicated.append(tag)
    return deduplicated
