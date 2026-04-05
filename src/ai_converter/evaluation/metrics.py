"""Deterministic evaluation metrics for offline benchmark runs."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.validation import AcceptanceReport


class CaseAccuracyMetrics(BaseModel):
    """Per-case field-accuracy metrics for one benchmark output."""

    model_config = ConfigDict(extra="forbid")

    matched_required_fields: int = Field(ge=0)
    total_required_fields: int = Field(ge=0)
    matched_fields: int = Field(ge=0)
    total_fields: int = Field(ge=0)
    required_field_accuracy: float = Field(ge=0.0, le=1.0)
    field_accuracy: float = Field(ge=0.0, le=1.0)


class BenchmarkMetrics(BaseModel):
    """Aggregate benchmark metrics for one subject/scenario run."""

    model_config = ConfigDict(extra="forbid")

    required_field_accuracy: float = Field(ge=0.0, le=1.0)
    macro_field_accuracy: float = Field(ge=0.0, le=1.0)
    micro_field_accuracy: float = Field(ge=0.0, le=1.0)
    pass_at_1: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    repair_iterations: int = Field(ge=0)
    preparation_seconds: float = Field(ge=0.0, exclude=True)
    runtime_seconds: float = Field(ge=0.0, exclude=True)


def compute_case_accuracy(
    expected_output: dict[str, Any],
    actual_output: dict[str, Any] | None,
    *,
    required_fields: Sequence[str] = (),
) -> CaseAccuracyMetrics:
    """Compute deterministic field-accuracy metrics for one case.

    Args:
        expected_output: Expected target-side output.
        actual_output: Actual converter output, if execution succeeded.
        required_fields: Canonical target paths considered required.

    Returns:
        Per-case field-accuracy metrics.
    """

    expected_flat = _flatten_mapping(expected_output)
    actual_flat = _flatten_mapping(actual_output or {})
    required = list(required_fields) if required_fields else list(expected_flat)

    matched_fields = sum(
        1
        for path, expected_value in expected_flat.items()
        if actual_flat.get(path) == expected_value
    )
    matched_required = sum(
        1
        for path in required
        if path in expected_flat and actual_flat.get(path) == expected_flat[path]
    )

    total_fields = len(expected_flat)
    total_required = len([path for path in required if path in expected_flat])
    return CaseAccuracyMetrics(
        matched_required_fields=matched_required,
        total_required_fields=total_required,
        matched_fields=matched_fields,
        total_fields=total_fields,
        required_field_accuracy=0.0 if total_required == 0 else matched_required / total_required,
        field_accuracy=0.0 if total_fields == 0 else matched_fields / total_fields,
    )


def compute_required_field_accuracy(
    case_metrics: Sequence[CaseAccuracyMetrics],
) -> float:
    """Compute overall required-field accuracy across benchmark cases.

    Args:
        case_metrics: Per-case field-accuracy metrics.

    Returns:
        Overall required-field accuracy across all cases.
    """

    total_required = sum(metric.total_required_fields for metric in case_metrics)
    matched_required = sum(metric.matched_required_fields for metric in case_metrics)
    return 0.0 if total_required == 0 else matched_required / total_required


def compute_macro_micro_accuracy(
    case_metrics: Sequence[CaseAccuracyMetrics],
) -> tuple[float, float]:
    """Compute macro and micro field accuracy across benchmark cases.

    Args:
        case_metrics: Per-case field-accuracy metrics.

    Returns:
        Tuple of ``(macro_field_accuracy, micro_field_accuracy)``.
    """

    if not case_metrics:
        return 0.0, 0.0
    macro = mean(metric.field_accuracy for metric in case_metrics)
    total_fields = sum(metric.total_fields for metric in case_metrics)
    matched_fields = sum(metric.matched_fields for metric in case_metrics)
    micro = 0.0 if total_fields == 0 else matched_fields / total_fields
    return macro, micro


def build_benchmark_metrics(
    case_metrics: Sequence[CaseAccuracyMetrics],
    *,
    preparation_seconds: float,
    runtime_seconds: float,
    execution_success: bool,
    acceptance_report: AcceptanceReport | None = None,
) -> BenchmarkMetrics:
    """Build aggregate benchmark metrics for one benchmark run.

    Args:
        case_metrics: Per-case field-accuracy metrics.
        preparation_seconds: Time spent preparing the converter under test.
        runtime_seconds: Total time spent executing the benchmark cases.
        execution_success: Whether all benchmark cases executed successfully.
        acceptance_report: Optional acceptance report reused from the validation layer.

    Returns:
        Aggregate benchmark metrics.
    """

    required_field_accuracy = compute_required_field_accuracy(case_metrics)
    macro_field_accuracy, micro_field_accuracy = compute_macro_micro_accuracy(case_metrics)

    all_cases_match = all(metric.field_accuracy == 1.0 for metric in case_metrics)
    if acceptance_report is not None:
        pass_at_1 = 1.0 if (
            execution_success
            and acceptance_report.execution_success
            and acceptance_report.structural_validity
            and acceptance_report.semantic_validity
            and all_cases_match
        ) else 0.0
        coverage = acceptance_report.coverage
        repair_iterations = acceptance_report.repair_iterations
    else:
        pass_at_1 = 1.0 if execution_success and all_cases_match else 0.0
        coverage = 0.0 if not case_metrics else sum(metric.field_accuracy == 1.0 for metric in case_metrics) / len(case_metrics)
        repair_iterations = 0

    return BenchmarkMetrics(
        required_field_accuracy=required_field_accuracy,
        macro_field_accuracy=macro_field_accuracy,
        micro_field_accuracy=micro_field_accuracy,
        pass_at_1=pass_at_1,
        coverage=coverage,
        repair_iterations=repair_iterations,
        preparation_seconds=preparation_seconds,
        runtime_seconds=runtime_seconds,
    )


def _flatten_mapping(mapping: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionaries into dotted target paths.

    Args:
        mapping: Nested target-side dictionary.
        prefix: Current dotted prefix.

    Returns:
        Flattened path-to-value mapping.
    """

    flattened: dict[str, Any] = {}
    for key, value in mapping.items():
        path = key if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            flattened.update(_flatten_mapping(value, prefix=path))
            continue
        flattened[path] = value
    return flattened
