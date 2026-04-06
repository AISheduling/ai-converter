"""Aggregation helpers for repeated benchmark experiment summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .benchmark import BenchmarkCaseResult, BenchmarkExperimentResult, BenchmarkSubjectResult
from .metrics import compute_macro_micro_accuracy, compute_required_field_accuracy


class BenchmarkMetricSummaryStats(BaseModel):
    """Distribution statistics for one repeated benchmark metric."""

    model_config = ConfigDict(extra="forbid")

    mean: float
    median: float
    standard_deviation: float = Field(ge=0.0)
    minimum: float
    maximum: float
    q1: float
    q3: float
    iqr: float = Field(ge=0.0)


class BenchmarkExperimentMetricRow(BaseModel):
    """Long-form repeated-run metric row suitable for boxplot tooling."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    experiment_name: str | None = None
    scenario_name: str
    subject_name: str
    subject_kind: str
    metric_group: Literal["benchmark", "stage", "telemetry"]
    metric_name: str
    value: float
    bundle_kind: str | None = None
    dataset_id: str | None = None
    template_id: str | None = None
    drift_id: str | None = None
    drift_type: str | None = None
    severity: str | None = None
    compatibility_class: str | None = None
    tags: list[str] = Field(default_factory=list)


class BenchmarkExperimentSummaryRow(BaseModel):
    """Grouped repeated-run summary row for one metric."""

    model_config = ConfigDict(extra="forbid")

    group_type: str
    group_label: str
    scenario_name: str | None = None
    subject_name: str
    subject_kind: str
    metric_group: Literal["benchmark", "stage", "telemetry"]
    metric_name: str
    run_count: int = Field(ge=1)
    bundle_kind: str | None = None
    dataset_id: str | None = None
    template_id: str | None = None
    drift_id: str | None = None
    drift_type: str | None = None
    severity: str | None = None
    compatibility_class: str | None = None
    tags: list[str] = Field(default_factory=list)
    statistics: BenchmarkMetricSummaryStats


class BenchmarkExperimentSummary(BaseModel):
    """Top-level grouped summary for one repeated benchmark experiment."""

    model_config = ConfigDict(extra="forbid")

    experiment_name: str | None = None
    run_count: int = Field(ge=0)
    summary_rows: list[BenchmarkExperimentSummaryRow] = Field(default_factory=list)


@dataclass(slots=True)
class _MetricGroupDimensions:
    """Stable grouping dimensions derived from synthetic benchmark tags."""

    bundle_kind: str | None
    dataset_id: str | None
    template_id: str | None
    drift_id: str | None
    drift_type: str | None
    severity: str | None
    compatibility_class: str | None
    tags: list[str]


@dataclass(slots=True)
class _Observation:
    """One per-run grouped observation emitted before repeated-run rollup."""

    run_id: str
    experiment_name: str | None
    scenario_name: str
    subject_name: str
    subject_kind: str
    dimensions: _MetricGroupDimensions
    benchmark_metrics: dict[str, float]
    stage_metrics: dict[str, float]


def build_benchmark_boxplot_rows(
    result: BenchmarkExperimentResult,
) -> list[BenchmarkExperimentMetricRow]:
    """Build long-form repeated-run rows from canonical benchmark metrics.

    Args:
        result: Repeated benchmark experiment result to flatten.

    Returns:
        Deterministic long-form metric rows.
    """

    rows: list[BenchmarkExperimentMetricRow] = []
    for observation in _build_observations(result):
        rows.extend(
            _build_metric_rows(
                observation=observation,
                metric_group="benchmark",
                metrics=observation.benchmark_metrics,
            )
        )
        rows.extend(
            _build_metric_rows(
                observation=observation,
                metric_group="stage",
                metrics=observation.stage_metrics,
            )
        )
    return rows


def build_benchmark_telemetry_boxplot_rows(
    telemetry_sidecars: dict[str, str | Path] | list[str | Path],
    *,
    experiment_name: str | None = None,
) -> list[BenchmarkExperimentMetricRow]:
    """Build long-form telemetry rows from per-run sidecar artifacts.

    Args:
        telemetry_sidecars: Mapping or sequence of telemetry sidecar paths.
        experiment_name: Optional experiment label copied onto every row.

    Returns:
        Deterministic telemetry rows derived from sidecar artifacts.
    """

    rows: list[BenchmarkExperimentMetricRow] = []
    for run_id, sidecar_path in _iter_sidecar_items(telemetry_sidecars):
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        for scenario_entry in payload.get("scenario_results", []):
            scenario_name = str(scenario_entry["scenario_name"])
            scenario_dimensions = _build_dimensions_from_tags(
                [str(tag) for tag in scenario_entry.get("tags", [])]
            )
            for subject_entry in scenario_entry.get("subject_results", []):
                subject_name = str(subject_entry["subject_name"])
                subject_kind = str(subject_entry["subject_kind"])
                rows.append(
                    _build_telemetry_row(
                        run_id=run_id,
                        experiment_name=experiment_name,
                        scenario_name=scenario_name,
                        subject_name=subject_name,
                        subject_kind=subject_kind,
                        dimensions=scenario_dimensions,
                        metric_name="preparation_seconds",
                        value=float(subject_entry["preparation_seconds"]),
                    )
                )
                rows.append(
                    _build_telemetry_row(
                        run_id=run_id,
                        experiment_name=experiment_name,
                        scenario_name=scenario_name,
                        subject_name=subject_name,
                        subject_kind=subject_kind,
                        dimensions=scenario_dimensions,
                        metric_name="runtime_seconds",
                        value=float(subject_entry["runtime_seconds"]),
                    )
                )
                for case_entry in subject_entry.get("case_results", []):
                    case_dimensions = _build_dimensions_from_tags(
                        [str(tag) for tag in case_entry.get("tags", [])]
                    )
                    rows.append(
                        _build_telemetry_row(
                            run_id=run_id,
                            experiment_name=experiment_name,
                            scenario_name=scenario_name,
                            subject_name=subject_name,
                            subject_kind=subject_kind,
                            dimensions=case_dimensions if case_dimensions.tags else scenario_dimensions,
                            metric_name="case_runtime_seconds",
                            value=float(case_entry["runtime_seconds"]),
                        )
                    )
    return rows


def summarize_benchmark_experiment(
    result: BenchmarkExperimentResult,
) -> BenchmarkExperimentSummary:
    """Summarize repeated benchmark runs from the canonical evaluation layer.

    Args:
        result: Repeated benchmark experiment result to summarize.

    Returns:
        Grouped repeated-run summary rows.
    """

    rows = build_benchmark_boxplot_rows(result)
    return summarize_benchmark_metric_rows(
        rows,
        experiment_name=result.experiment_name,
        run_count=len(result.runs),
    )


def summarize_benchmark_metric_rows(
    rows: list[BenchmarkExperimentMetricRow],
    *,
    experiment_name: str | None = None,
    run_count: int | None = None,
) -> BenchmarkExperimentSummary:
    """Summarize long-form repeated-run rows into grouped summary rows.

    Args:
        rows: Long-form repeated-run metric rows.
        experiment_name: Optional experiment label copied to the summary payload.
        run_count: Optional explicit run count. When omitted, inferred from the
            distinct run ids present in ``rows``.

    Returns:
        Grouped summary rows for scenario, bundle-kind, drift-type, severity,
        and compatibility-class comparisons.
    """

    grouped_rows: list[BenchmarkExperimentSummaryRow] = []
    grouped_rows.extend(
        _summarize_rows(
            rows,
            group_type="scenario_subject",
            key_builder=lambda row: (
                row.scenario_name,
                row.subject_name,
                row.subject_kind,
                row.metric_group,
                row.metric_name,
                row.bundle_kind,
                row.dataset_id,
                row.template_id,
                row.drift_id,
                row.drift_type,
                row.severity,
                row.compatibility_class,
                tuple(row.tags),
            ),
            label_builder=lambda row: row.scenario_name,
            scenario_name_builder=lambda row: row.scenario_name,
        )
    )
    grouped_rows.extend(
        _summarize_rows(
            [row for row in rows if row.bundle_kind is not None],
            group_type="bundle_kind_subject",
            key_builder=lambda row: (
                row.bundle_kind,
                row.subject_name,
                row.subject_kind,
                row.metric_group,
                row.metric_name,
            ),
            label_builder=lambda row: row.bundle_kind or "unknown",
            scenario_name_builder=lambda row: None,
            metadata_builder=lambda row: {
                "bundle_kind": row.bundle_kind,
                "dataset_id": None,
                "template_id": None,
                "drift_id": None,
                "drift_type": None,
                "severity": None,
                "compatibility_class": None,
                "tags": [tag for tag in row.tags if tag in {"synthetic", "base", "drift", "mixed"}],
            },
        )
    )
    grouped_rows.extend(
        _summarize_rows(
            [row for row in rows if row.drift_type is not None],
            group_type="drift_type_subject",
            key_builder=lambda row: (
                row.drift_type,
                row.subject_name,
                row.subject_kind,
                row.metric_group,
                row.metric_name,
            ),
            label_builder=lambda row: row.drift_type or "unknown",
            scenario_name_builder=lambda row: None,
            metadata_builder=lambda row: {
                "bundle_kind": "drift",
                "dataset_id": None,
                "template_id": None,
                "drift_id": None,
                "drift_type": row.drift_type,
                "severity": None,
                "compatibility_class": None,
                "tags": [
                    tag
                    for tag in row.tags
                    if tag == "synthetic" or tag.startswith("drift_type:")
                ],
            },
        )
    )
    grouped_rows.extend(
        _summarize_rows(
            [row for row in rows if row.severity is not None],
            group_type="severity_subject",
            key_builder=lambda row: (
                row.severity,
                row.subject_name,
                row.subject_kind,
                row.metric_group,
                row.metric_name,
            ),
            label_builder=lambda row: row.severity or "unknown",
            scenario_name_builder=lambda row: None,
            metadata_builder=lambda row: {
                "bundle_kind": "drift" if row.metric_group != "telemetry" or row.bundle_kind == "drift" else row.bundle_kind,
                "dataset_id": None,
                "template_id": None,
                "drift_id": None,
                "drift_type": None,
                "severity": row.severity,
                "compatibility_class": None,
                "tags": [
                    tag
                    for tag in row.tags
                    if tag == "synthetic" or tag.startswith("severity:")
                ],
            },
        )
    )
    grouped_rows.extend(
        _summarize_rows(
            [row for row in rows if row.compatibility_class is not None],
            group_type="compatibility_class_subject",
            key_builder=lambda row: (
                row.compatibility_class,
                row.subject_name,
                row.subject_kind,
                row.metric_group,
                row.metric_name,
            ),
            label_builder=lambda row: row.compatibility_class or "unknown",
            scenario_name_builder=lambda row: None,
            metadata_builder=lambda row: {
                "bundle_kind": "drift" if row.metric_group != "telemetry" or row.bundle_kind == "drift" else row.bundle_kind,
                "dataset_id": None,
                "template_id": None,
                "drift_id": None,
                "drift_type": None,
                "severity": None,
                "compatibility_class": row.compatibility_class,
                "tags": [
                    tag
                    for tag in row.tags
                    if tag == "synthetic" or tag.startswith("compatibility:")
                ],
            },
        )
    )

    resolved_run_count = run_count
    if resolved_run_count is None:
        resolved_run_count = len({row.run_id for row in rows})

    return BenchmarkExperimentSummary(
        experiment_name=experiment_name,
        run_count=resolved_run_count,
        summary_rows=sorted(
            grouped_rows,
            key=lambda row: (
                row.group_type,
                row.group_label,
                row.metric_group,
                row.metric_name,
                row.subject_name,
                row.subject_kind,
                row.scenario_name or "",
            ),
        ),
    )


def summarize_benchmark_telemetry(
    telemetry_sidecars: dict[str, str | Path] | list[str | Path],
    *,
    experiment_name: str | None = None,
) -> BenchmarkExperimentSummary:
    """Summarize telemetry sidecars without touching canonical run payloads.

    Args:
        telemetry_sidecars: Mapping or sequence of telemetry sidecar paths.
        experiment_name: Optional experiment label copied to the summary payload.

    Returns:
        Grouped summary rows derived strictly from telemetry sidecar artifacts.
    """

    rows = build_benchmark_telemetry_boxplot_rows(
        telemetry_sidecars,
        experiment_name=experiment_name,
    )
    return summarize_benchmark_metric_rows(
        rows,
        experiment_name=experiment_name,
    )


def _build_observations(result: BenchmarkExperimentResult) -> list[_Observation]:
    """Build per-run grouped observations before repeated-run rollup."""

    observations: list[_Observation] = []
    for run in result.runs:
        for scenario_result in run.result.scenario_results:
            for subject_result in scenario_result.subject_results:
                grouped_cases = _group_case_results(subject_result.case_results)
                for dimensions, grouped_case_results in grouped_cases:
                    observations.append(
                        _Observation(
                            run_id=run.run_id,
                            experiment_name=result.experiment_name,
                            scenario_name=scenario_result.scenario_name,
                            subject_name=subject_result.subject_name,
                            subject_kind=subject_result.subject_kind,
                            dimensions=dimensions,
                            benchmark_metrics=_build_observation_metrics(
                                case_results=grouped_case_results,
                                subject_result=subject_result,
                            ),
                            stage_metrics=_build_observation_stage_metrics(
                                case_results=grouped_case_results,
                                subject_result=subject_result,
                            ),
                        )
                    )
    return observations


def _group_case_results(
    case_results: list[BenchmarkCaseResult],
) -> list[tuple[_MetricGroupDimensions, list[BenchmarkCaseResult]]]:
    """Group case results by deterministic synthetic benchmark dimensions."""

    grouped: dict[tuple[str | None, ...], dict[str, Any]] = {}
    for case_result in case_results:
        dimensions = _build_dimensions_from_tags(case_result.tags)
        key = (
            dimensions.bundle_kind,
            dimensions.dataset_id,
            dimensions.template_id,
            dimensions.drift_id,
            dimensions.drift_type,
            dimensions.severity,
            dimensions.compatibility_class,
            tuple(dimensions.tags),
        )
        entry = grouped.setdefault(
            key,
            {
                "dimensions": dimensions,
                "case_results": [],
            },
        )
        entry["case_results"].append(case_result)

    return [
        (grouped[key]["dimensions"], grouped[key]["case_results"])
        for key in sorted(grouped)
    ]


def _build_dimensions_from_tags(tags: list[str]) -> _MetricGroupDimensions:
    """Build stable synthetic benchmark grouping dimensions from tags."""

    has_base = "base" in tags
    has_drift = "drift" in tags
    if has_base and has_drift:
        bundle_kind = "mixed"
    elif has_drift:
        bundle_kind = "drift"
    elif has_base:
        bundle_kind = "base"
    else:
        bundle_kind = None

    dataset_id = _extract_tag_value(tags, "dataset:")
    template_id = _extract_tag_value(tags, "template:")
    drift_id = _extract_tag_value(tags, "drift_id:")
    drift_type = _extract_tag_value(tags, "drift_type:")
    severity = _extract_tag_value(tags, "severity:")
    compatibility_class = _extract_tag_value(tags, "compatibility:")

    normalized_tags: list[str] = []
    if "synthetic" in tags:
        normalized_tags.append("synthetic")
    if bundle_kind is not None:
        normalized_tags.append(bundle_kind)
    if dataset_id is not None:
        normalized_tags.append(f"dataset:{dataset_id}")
    if template_id is not None:
        normalized_tags.append(f"template:{template_id}")
    if drift_id is not None:
        normalized_tags.append(f"drift_id:{drift_id}")
    if drift_type is not None:
        normalized_tags.append(f"drift_type:{drift_type}")
    if compatibility_class is not None:
        normalized_tags.append(f"compatibility:{compatibility_class}")
    if severity is not None:
        normalized_tags.append(f"severity:{severity}")

    return _MetricGroupDimensions(
        bundle_kind=bundle_kind,
        dataset_id=dataset_id,
        template_id=template_id,
        drift_id=drift_id,
        drift_type=drift_type,
        severity=severity,
        compatibility_class=compatibility_class,
        tags=normalized_tags,
    )


def _extract_tag_value(tags: list[str], prefix: str) -> str | None:
    """Extract one prefixed deterministic tag value when present."""

    for tag in tags:
        if tag.startswith(prefix):
            return tag.removeprefix(prefix)
    return None


def _build_metric_rows(
    *,
    observation: _Observation,
    metric_group: Literal["benchmark", "stage"],
    metrics: dict[str, float],
) -> list[BenchmarkExperimentMetricRow]:
    """Build long-form metric rows for one grouped repeated-run observation."""

    return [
        BenchmarkExperimentMetricRow(
            run_id=observation.run_id,
            experiment_name=observation.experiment_name,
            scenario_name=observation.scenario_name,
            subject_name=observation.subject_name,
            subject_kind=observation.subject_kind,
            metric_group=metric_group,
            metric_name=metric_name,
            value=value,
            bundle_kind=observation.dimensions.bundle_kind,
            dataset_id=observation.dimensions.dataset_id,
            template_id=observation.dimensions.template_id,
            drift_id=observation.dimensions.drift_id,
            drift_type=observation.dimensions.drift_type,
            severity=observation.dimensions.severity,
            compatibility_class=observation.dimensions.compatibility_class,
            tags=list(observation.dimensions.tags),
        )
        for metric_name, value in sorted(metrics.items())
    ]


def _build_telemetry_row(
    *,
    run_id: str,
    experiment_name: str | None,
    scenario_name: str,
    subject_name: str,
    subject_kind: str,
    dimensions: _MetricGroupDimensions,
    metric_name: str,
    value: float,
) -> BenchmarkExperimentMetricRow:
    """Build one long-form telemetry row from sidecar-derived timing data."""

    return BenchmarkExperimentMetricRow(
        run_id=run_id,
        experiment_name=experiment_name,
        scenario_name=scenario_name,
        subject_name=subject_name,
        subject_kind=subject_kind,
        metric_group="telemetry",
        metric_name=metric_name,
        value=value,
        bundle_kind=dimensions.bundle_kind,
        dataset_id=dimensions.dataset_id,
        template_id=dimensions.template_id,
        drift_id=dimensions.drift_id,
        drift_type=dimensions.drift_type,
        severity=dimensions.severity,
        compatibility_class=dimensions.compatibility_class,
        tags=list(dimensions.tags),
    )


def _build_observation_metrics(
    *,
    case_results: list[BenchmarkCaseResult],
    subject_result: BenchmarkSubjectResult,
) -> dict[str, float]:
    """Build aggregate benchmark metrics for one grouped observation."""

    case_metrics = [case_result.metrics for case_result in case_results]
    required_field_accuracy = compute_required_field_accuracy(case_metrics)
    macro_field_accuracy, micro_field_accuracy = compute_macro_micro_accuracy(case_metrics)
    runtime_validity = [_is_runtime_valid(case_result) for case_result in case_results]
    execution_success = all(case_result.execution_success for case_result in case_results)
    coverage = 0.0 if not case_results else sum(runtime_validity) / len(case_results)
    pass_at_1 = 1.0 if (
        execution_success
        and coverage == 1.0
        and all(case_result.metrics.field_accuracy == 1.0 for case_result in case_results)
    ) else 0.0
    return {
        "required_field_accuracy": required_field_accuracy,
        "macro_field_accuracy": macro_field_accuracy,
        "micro_field_accuracy": micro_field_accuracy,
        "pass_at_1": pass_at_1,
        "coverage": coverage,
        "repair_iterations": float(subject_result.metrics.repair_iterations),
    }


def _build_observation_stage_metrics(
    *,
    case_results: list[BenchmarkCaseResult],
    subject_result: BenchmarkSubjectResult,
) -> dict[str, float]:
    """Build stage metrics for one grouped repeated-run observation."""

    existing = subject_result.metrics.stage_metrics
    total_cases = len(case_results)
    if total_cases == 0:
        execution_success_rate = 0.0
        runtime_validity_rate = 0.0
    else:
        execution_success_rate = sum(case_result.execution_success for case_result in case_results) / total_cases
        runtime_validity_rate = sum(_is_runtime_valid(case_result) for case_result in case_results) / total_cases

    structural_values = [
        float(bool(case_result.structural_validity))
        for case_result in case_results
        if case_result.structural_validity is not None
    ]
    semantic_values = [
        float(bool(case_result.semantic_validity))
        for case_result in case_results
        if case_result.semantic_validity is not None
    ]

    payload: dict[str, float] = {
        "stage.build_success": float(
            True if existing is None or existing.build_success is None else existing.build_success
        ),
        "stage.execution_success_rate": execution_success_rate,
        "stage.runtime_validity_rate": runtime_validity_rate,
    }
    if structural_values:
        payload["stage.structural_validity_rate"] = mean(structural_values)
    if semantic_values:
        payload["stage.semantic_validity_rate"] = mean(semantic_values)
    if existing is not None and existing.source_structure_recovery is not None:
        payload["stage.source_structure_recovery"] = existing.source_structure_recovery
    if existing is not None and existing.mapping_quality is not None:
        payload["stage.mapping_quality"] = existing.mapping_quality
    return payload


def _is_runtime_valid(case_result: BenchmarkCaseResult) -> bool:
    """Return whether one case passed the end-to-end runtime validation path."""

    if case_result.structural_validity is None or case_result.semantic_validity is None:
        return case_result.execution_success
    return (
        case_result.execution_success
        and bool(case_result.structural_validity)
        and bool(case_result.semantic_validity)
    )


def _iter_sidecar_items(
    telemetry_sidecars: dict[str, str | Path] | list[str | Path],
) -> list[tuple[str, Path]]:
    """Normalize telemetry sidecar inputs into sorted run/path pairs."""

    if isinstance(telemetry_sidecars, dict):
        return [
            (run_id, Path(path))
            for run_id, path in sorted(telemetry_sidecars.items())
        ]
    return [
        (Path(path).parent.name, Path(path))
        for path in sorted(telemetry_sidecars, key=lambda value: str(value))
    ]


def _build_group_label(row: BenchmarkExperimentMetricRow) -> str:
    """Build a compact deterministic label for one grouped metric row."""

    parts: list[str] = []
    if row.bundle_kind is not None:
        parts.append(row.bundle_kind)
    if row.drift_type is not None:
        parts.append(row.drift_type)
    if row.compatibility_class is not None:
        parts.append(row.compatibility_class)
    if row.severity is not None:
        parts.append(row.severity)
    return "/".join(parts) if parts else "all"


def _summarize_rows(
    rows: list[BenchmarkExperimentMetricRow],
    *,
    group_type: str,
    key_builder: Any,
    label_builder: Any,
    scenario_name_builder: Any,
    metadata_builder: Any | None = None,
) -> list[BenchmarkExperimentSummaryRow]:
    """Summarize one family of grouped metric rows."""

    grouped: dict[tuple[Any, ...], list[BenchmarkExperimentMetricRow]] = {}
    for row in rows:
        grouped.setdefault(tuple(key_builder(row)), []).append(row)

    summaries: list[BenchmarkExperimentSummaryRow] = []
    for key in sorted(grouped):
        grouped_rows = grouped[key]
        first = grouped_rows[0]
        metadata = (
            {
                "bundle_kind": first.bundle_kind,
                "dataset_id": first.dataset_id,
                "template_id": first.template_id,
                "drift_id": first.drift_id,
                "drift_type": first.drift_type,
                "severity": first.severity,
                "compatibility_class": first.compatibility_class,
                "tags": list(first.tags),
            }
            if metadata_builder is None
            else metadata_builder(first)
        )
        summaries.append(
            BenchmarkExperimentSummaryRow(
                group_type=group_type,
                group_label=f"{label_builder(first)} / {first.subject_name}",
                scenario_name=scenario_name_builder(first),
                subject_name=first.subject_name,
                subject_kind=first.subject_kind,
                metric_group=first.metric_group,
                metric_name=first.metric_name,
                run_count=len({row.run_id for row in grouped_rows}),
                bundle_kind=metadata["bundle_kind"],
                dataset_id=metadata["dataset_id"],
                template_id=metadata["template_id"],
                drift_id=metadata["drift_id"],
                drift_type=metadata["drift_type"],
                severity=metadata["severity"],
                compatibility_class=metadata["compatibility_class"],
                tags=list(metadata["tags"]),
                statistics=_summarize_numeric_values([row.value for row in grouped_rows]),
            )
        )
    return summaries


def _summarize_numeric_values(values: list[float]) -> BenchmarkMetricSummaryStats:
    """Summarize one numeric repeated-run series with deterministic quartiles."""

    ordered = sorted(float(value) for value in values)
    q1 = _percentile(ordered, 0.25)
    q3 = _percentile(ordered, 0.75)
    return BenchmarkMetricSummaryStats(
        mean=mean(ordered),
        median=median(ordered),
        standard_deviation=pstdev(ordered),
        minimum=ordered[0],
        maximum=ordered[-1],
        q1=q1,
        q3=q3,
        iqr=q3 - q1,
    )


def _percentile(values: list[float], fraction: float) -> float:
    """Compute one percentile using deterministic linear interpolation.

    Args:
        values: Sorted numeric values.
        fraction: Percentile fraction between 0 and 1.

    Returns:
        Interpolated percentile value.
    """

    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    if lower_index == upper_index:
        return values[lower_index]

    lower_value = values[lower_index]
    upper_value = values[upper_index]
    weight = position - lower_index
    return lower_value + (upper_value - lower_value) * weight
