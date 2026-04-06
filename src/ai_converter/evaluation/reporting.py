"""Reporting helpers for canonical, telemetry, and Markdown benchmark outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .aggregation import (
    BenchmarkExperimentMetricRow,
    BenchmarkExperimentSummary,
    build_benchmark_boxplot_rows,
    build_benchmark_telemetry_boxplot_rows,
    summarize_benchmark_experiment,
    summarize_benchmark_telemetry,
)
from .benchmark import BenchmarkExperimentResult, BenchmarkRunResult

_TIMING_FIELD_NAMES = frozenset({"preparation_seconds", "runtime_seconds"})


def write_benchmark_telemetry_json(
    result: BenchmarkRunResult,
    path: str | Path,
) -> Path:
    """Write timing-only benchmark telemetry as JSON.

    Args:
        result: Benchmark run result to project into telemetry.
        path: Output path for the telemetry JSON artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    payload = _build_benchmark_telemetry_payload(result)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def write_benchmark_json(result: BenchmarkRunResult, path: str | Path) -> Path:
    """Write one canonical benchmark result bundle as formatted JSON.

    Args:
        result: Benchmark run result to serialize canonically.
        path: Output path for the JSON artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    payload = _build_canonical_benchmark_payload(result)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def write_benchmark_csv(result: BenchmarkRunResult, path: str | Path) -> Path:
    """Write canonical flattened per-case benchmark rows as CSV.

    Args:
        result: Benchmark run result to flatten canonically.
        path: Output path for the CSV artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario",
                "subject",
                "subject_kind",
                "case",
                "execution_success",
                "required_field_accuracy",
                "field_accuracy",
                "structural_validity",
                "semantic_validity",
            ],
        )
        writer.writeheader()
        for scenario_result in result.scenario_results:
            for subject_result in scenario_result.subject_results:
                for case_result in subject_result.case_results:
                    writer.writerow(
                        {
                            "scenario": scenario_result.scenario_name,
                            "subject": subject_result.subject_name,
                            "subject_kind": subject_result.subject_kind,
                            "case": case_result.name,
                            "execution_success": case_result.execution_success,
                            "required_field_accuracy": case_result.metrics.required_field_accuracy,
                            "field_accuracy": case_result.metrics.field_accuracy,
                            "structural_validity": case_result.structural_validity,
                            "semantic_validity": case_result.semantic_validity,
                        }
                    )
    return output_path


def write_benchmark_experiment_summary_json(
    summary: BenchmarkExperimentSummary,
    path: str | Path,
) -> Path:
    """Write grouped repeated-run summary data as formatted JSON.

    Args:
        summary: Repeated-run summary to serialize.
        path: Output path for the summary JSON artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    output_path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_benchmark_experiment_summary_csv(
    summary: BenchmarkExperimentSummary,
    path: str | Path,
) -> Path:
    """Write grouped repeated-run summary rows as CSV.

    Args:
        summary: Repeated-run summary to flatten.
        path: Output path for the summary CSV artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "group_type",
                "group_label",
                "scenario_name",
                "subject_name",
                "subject_kind",
                "metric_group",
                "metric_name",
                "run_count",
                "bundle_kind",
                "dataset_id",
                "template_id",
                "drift_id",
                "drift_type",
                "severity",
                "compatibility_class",
                "tags",
                "mean",
                "median",
                "standard_deviation",
                "minimum",
                "maximum",
                "q1",
                "q3",
                "iqr",
            ],
        )
        writer.writeheader()
        for row in summary.summary_rows:
            stats = row.statistics
            writer.writerow(
                {
                    "group_type": row.group_type,
                    "group_label": row.group_label,
                    "scenario_name": row.scenario_name,
                    "subject_name": row.subject_name,
                    "subject_kind": row.subject_kind,
                    "metric_group": row.metric_group,
                    "metric_name": row.metric_name,
                    "run_count": row.run_count,
                    "bundle_kind": row.bundle_kind,
                    "dataset_id": row.dataset_id,
                    "template_id": row.template_id,
                    "drift_id": row.drift_id,
                    "drift_type": row.drift_type,
                    "severity": row.severity,
                    "compatibility_class": row.compatibility_class,
                    "tags": ";".join(row.tags),
                    "mean": stats.mean,
                    "median": stats.median,
                    "standard_deviation": stats.standard_deviation,
                    "minimum": stats.minimum,
                    "maximum": stats.maximum,
                    "q1": stats.q1,
                    "q3": stats.q3,
                    "iqr": stats.iqr,
                }
            )
    return output_path


def write_benchmark_boxplot_csv(
    rows: list[BenchmarkExperimentMetricRow],
    path: str | Path,
) -> Path:
    """Write long-format repeated-run metric rows as CSV.

    Args:
        rows: Long-format metric rows suitable for boxplots.
        path: Output path for the boxplot-friendly CSV artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "experiment_name",
                "scenario_name",
                "subject_name",
                "subject_kind",
                "metric_group",
                "metric_name",
                "value",
                "bundle_kind",
                "dataset_id",
                "template_id",
                "drift_id",
                "drift_type",
                "severity",
                "compatibility_class",
                "tags",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "run_id": row.run_id,
                    "experiment_name": row.experiment_name,
                    "scenario_name": row.scenario_name,
                    "subject_name": row.subject_name,
                    "subject_kind": row.subject_kind,
                    "metric_group": row.metric_group,
                    "metric_name": row.metric_name,
                    "value": row.value,
                    "bundle_kind": row.bundle_kind,
                    "dataset_id": row.dataset_id,
                    "template_id": row.template_id,
                    "drift_id": row.drift_id,
                    "drift_type": row.drift_type,
                    "severity": row.severity,
                    "compatibility_class": row.compatibility_class,
                    "tags": ";".join(row.tags),
                }
            )
    return output_path


def render_benchmark_markdown(result: BenchmarkRunResult) -> str:
    """Render a Markdown summary for one benchmark run result.

    Args:
        result: Benchmark run result to summarize.

    Returns:
        Human-readable Markdown summary.
    """

    lines = ["# Benchmark Summary", ""]
    for scenario_result in result.scenario_results:
        lines.append(f"## Scenario: {scenario_result.scenario_name}")
        lines.append("")
        lines.append("| Subject | Kind | Required Acc. | Macro Acc. | Micro Acc. | Pass@1 | Coverage |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for subject_result in scenario_result.subject_results:
            metrics = subject_result.metrics
            lines.append(
                "| "
                f"{subject_result.subject_name} | "
                f"{subject_result.subject_kind} | "
                f"{metrics.required_field_accuracy:.3f} | "
                f"{metrics.macro_field_accuracy:.3f} | "
                f"{metrics.micro_field_accuracy:.3f} | "
                f"{metrics.pass_at_1:.3f} | "
                f"{metrics.coverage:.3f} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_benchmark_experiment_markdown(
    result: BenchmarkExperimentResult,
    run_manifest: list[dict[str, Any]],
    *,
    summary: BenchmarkExperimentSummary | None = None,
    telemetry_summary: BenchmarkExperimentSummary | None = None,
) -> str:
    """Render a Markdown summary for one repeated benchmark experiment.

    Args:
        result: Experiment result to summarize.
        run_manifest: Deterministic run-manifest payload built during export.
        summary: Optional grouped repeated-run summary.
        telemetry_summary: Optional telemetry-only grouped summary.

    Returns:
        Human-readable Markdown summary for the experiment layout.
    """

    lines = ["# Benchmark Experiment Summary", ""]
    lines.append(f"Experiment: {result.experiment_name or 'unnamed'}")
    lines.append(f"Run count: {len(result.runs)}")
    lines.append("")
    lines.append("| Run ID | Scenarios | Tags | JSON | CSV | Markdown | Telemetry |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for run_entry in run_manifest:
        artifacts = run_entry["artifacts"]
        lines.append(
            "| "
            f"{run_entry['run_id']} | "
            f"{', '.join(run_entry['scenario_names'])} | "
            f"{', '.join(run_entry['scenario_tags']) or '-'} | "
            f"{artifacts['json']} | "
            f"{artifacts['csv']} | "
            f"{artifacts['markdown']} | "
            f"{artifacts.get('telemetry', '-')} |"
        )
    lines.append("")
    _append_summary_section(
        lines,
        title="Scenario Summary",
        rows=_select_summary_rows(
            summary,
            group_type="scenario_subject",
            metric_group="benchmark",
        ),
    )
    _append_summary_section(
        lines,
        title="Base vs Drift Comparison",
        rows=_select_summary_rows(
            summary,
            group_type="bundle_kind_subject",
            metric_group="benchmark",
        ),
    )
    _append_summary_section(
        lines,
        title="Drift Class Summary",
        rows=_select_summary_rows(
            summary,
            group_type="drift_type_subject",
            metric_group="benchmark",
        ),
    )
    _append_summary_section(
        lines,
        title="Stage Summary",
        rows=_select_summary_rows(
            summary,
            group_type="scenario_subject",
            metric_group="stage",
        ),
    )
    _append_summary_section(
        lines,
        title="Timing Summary",
        rows=_select_summary_rows(
            telemetry_summary,
            group_type="scenario_subject",
            metric_group="telemetry",
        ),
    )
    return "\n".join(lines)


def write_benchmark_markdown(result: BenchmarkRunResult, path: str | Path) -> Path:
    """Write one benchmark result bundle as Markdown.

    Args:
        result: Benchmark run result to summarize.
        path: Output path for the Markdown artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    output_path.write_text(render_benchmark_markdown(result), encoding="utf-8")
    return output_path


def export_benchmark_reports(
    result: BenchmarkRunResult,
    output_dir: str | Path,
    *,
    stem: str = "benchmark",
    include_telemetry: bool = False,
) -> dict[str, Path]:
    """Write canonical benchmark reports into one directory.

    Args:
        result: Benchmark run result to export.
        output_dir: Directory where artifacts should be written.
        stem: Shared filename prefix for the generated artifacts.
        include_telemetry: When ``True``, also emit a timing-only telemetry
            sidecar that is intentionally separate from canonical reports.

    Returns:
        Mapping from artifact type to output path.
    """

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / f"{stem}.json",
        "csv": directory / f"{stem}.csv",
        "markdown": directory / f"{stem}.md",
    }
    if include_telemetry:
        paths["telemetry"] = directory / f"{stem}.telemetry.json"
    write_benchmark_json(result, paths["json"])
    write_benchmark_csv(result, paths["csv"])
    write_benchmark_markdown(result, paths["markdown"])
    if include_telemetry:
        write_benchmark_telemetry_json(result, paths["telemetry"])
    return paths


def export_benchmark_experiment_reports(
    result: BenchmarkExperimentResult,
    output_dir: str | Path,
    *,
    stem: str = "benchmark",
    include_telemetry: bool = False,
) -> dict[str, Path]:
    """Write repeated benchmark runs into a deterministic grouped layout.

    Args:
        result: Repeated benchmark experiment result to export.
        output_dir: Directory where grouped artifacts should be written.
        stem: Shared filename prefix for per-run artifacts.
        include_telemetry: When ``True``, also emit per-run telemetry sidecars.

    Returns:
        Mapping from artifact type to output path.
    """

    directory = Path(output_dir)
    runs_dir = directory / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_manifest: list[dict[str, Any]] = []
    telemetry_paths_by_run: dict[str, Path] = {}
    for run in result.runs:
        run_dir = runs_dir / run.run_id
        artifact_paths = export_benchmark_reports(
            run.result,
            run_dir,
            stem=stem,
            include_telemetry=include_telemetry,
        )
        run_manifest.append(
            _build_experiment_run_manifest(
                run_id=run.run_id,
                artifact_paths=artifact_paths,
                output_dir=directory,
                run_result=run.result,
            )
        )
        if include_telemetry:
            telemetry_paths_by_run[run.run_id] = artifact_paths["telemetry"]

    summary = summarize_benchmark_experiment(result)
    summary_rows = build_benchmark_boxplot_rows(result)
    summary_json_path = directory / f"{stem}.summary.json"
    summary_csv_path = directory / f"{stem}.summary.csv"
    boxplot_csv_path = directory / f"{stem}.boxplot.csv"
    write_benchmark_experiment_summary_json(summary, summary_json_path)
    write_benchmark_experiment_summary_csv(summary, summary_csv_path)
    write_benchmark_boxplot_csv(summary_rows, boxplot_csv_path)

    telemetry_summary: BenchmarkExperimentSummary | None = None
    telemetry_summary_json_path: Path | None = None
    telemetry_summary_csv_path: Path | None = None
    telemetry_boxplot_csv_path: Path | None = None
    if include_telemetry:
        telemetry_rows = build_benchmark_telemetry_boxplot_rows(
            telemetry_paths_by_run,
            experiment_name=result.experiment_name,
        )
        telemetry_summary = summarize_benchmark_telemetry(
            telemetry_paths_by_run,
            experiment_name=result.experiment_name,
        )
        telemetry_summary_json_path = directory / f"{stem}.telemetry.summary.json"
        telemetry_summary_csv_path = directory / f"{stem}.telemetry.summary.csv"
        telemetry_boxplot_csv_path = directory / f"{stem}.telemetry.boxplot.csv"
        write_benchmark_experiment_summary_json(
            telemetry_summary,
            telemetry_summary_json_path,
        )
        write_benchmark_experiment_summary_csv(
            telemetry_summary,
            telemetry_summary_csv_path,
        )
        write_benchmark_boxplot_csv(
            telemetry_rows,
            telemetry_boxplot_csv_path,
        )

    payload = _build_benchmark_experiment_payload(
        result=result,
        run_manifest=run_manifest,
        include_telemetry=include_telemetry,
        summary_artifacts={
            "summary_json": summary_json_path,
            "summary_csv": summary_csv_path,
            "boxplot_csv": boxplot_csv_path,
        },
        telemetry_artifacts=(
            None
            if not include_telemetry
            else {
                "summary_json": telemetry_summary_json_path,
                "summary_csv": telemetry_summary_csv_path,
                "boxplot_csv": telemetry_boxplot_csv_path,
            }
        ),
    )
    experiment_json_path = directory / f"{stem}.experiment.json"
    experiment_markdown_path = directory / f"{stem}.experiment.md"
    experiment_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    experiment_markdown_path.write_text(
        render_benchmark_experiment_markdown(
            result,
            run_manifest,
            summary=summary,
            telemetry_summary=telemetry_summary,
        ),
        encoding="utf-8",
    )
    paths: dict[str, Path] = {
        "experiment_json": experiment_json_path,
        "experiment_markdown": experiment_markdown_path,
        "runs_dir": runs_dir,
        "summary_json": summary_json_path,
        "summary_csv": summary_csv_path,
        "boxplot_csv": boxplot_csv_path,
    }
    if include_telemetry and telemetry_summary_json_path is not None:
        paths["telemetry_summary_json"] = telemetry_summary_json_path
        paths["telemetry_summary_csv"] = telemetry_summary_csv_path
        paths["telemetry_boxplot_csv"] = telemetry_boxplot_csv_path
    return paths


def _build_canonical_benchmark_payload(result: BenchmarkRunResult) -> dict[str, Any]:
    """Build the canonical machine-readable benchmark payload."""

    return _strip_timing_fields(result.model_dump(mode="python"))


def _build_benchmark_telemetry_payload(result: BenchmarkRunResult) -> dict[str, Any]:
    """Build a timing-only telemetry payload for optional sidecar export."""

    return {
        "scenario_results": [
            {
                "scenario_name": scenario_result.scenario_name,
                "tags": list(scenario_result.tags),
                "subject_results": [
                    {
                        "subject_name": subject_result.subject_name,
                        "subject_kind": subject_result.subject_kind,
                        "preparation_seconds": subject_result.preparation_seconds,
                        "runtime_seconds": subject_result.metrics.runtime_seconds,
                        "case_results": [
                            {
                                "name": case_result.name,
                                "tags": list(case_result.tags),
                                "runtime_seconds": case_result.runtime_seconds,
                            }
                            for case_result in subject_result.case_results
                        ],
                    }
                    for subject_result in scenario_result.subject_results
                ],
            }
            for scenario_result in result.scenario_results
        ]
    }


def _build_benchmark_experiment_payload(
    *,
    result: BenchmarkExperimentResult,
    run_manifest: list[dict[str, Any]],
    include_telemetry: bool,
    summary_artifacts: dict[str, Path],
    telemetry_artifacts: dict[str, Path | None] | None,
) -> dict[str, Any]:
    """Build a deterministic grouped-run manifest payload.

    Args:
        result: Repeated benchmark experiment result.
        run_manifest: Deterministic manifest entries for every exported run.
        include_telemetry: Whether per-run telemetry sidecars were exported.
        summary_artifacts: Grouped summary artifact paths for the experiment.
        telemetry_artifacts: Optional grouped telemetry artifact paths.

    Returns:
        Machine-readable grouped-run manifest.
    """

    payload = {
        "experiment_name": result.experiment_name,
        "run_count": len(result.runs),
        "include_telemetry": include_telemetry,
        "summary_artifacts": {
            name: str(path.name)
            for name, path in summary_artifacts.items()
        },
        "runs": run_manifest,
    }
    if telemetry_artifacts is not None:
        payload["telemetry_artifacts"] = {
            name: str(path.name)
            for name, path in telemetry_artifacts.items()
            if path is not None
        }
    return payload


def _build_experiment_run_manifest(
    *,
    run_id: str,
    artifact_paths: dict[str, Path],
    output_dir: Path,
    run_result: BenchmarkRunResult,
) -> dict[str, Any]:
    """Build one experiment-manifest entry for an exported run.

    Args:
        run_id: Deterministic run identifier.
        artifact_paths: Exported per-run artifact paths.
        output_dir: Experiment root used for relative paths.
        run_result: Benchmark run result that produced the artifacts.

    Returns:
        Deterministic manifest entry for the exported run.
    """

    scenario_tags = sorted(
        {
            tag
            for scenario_result in run_result.scenario_results
            for tag in scenario_result.tags
        }
    )
    return {
        "run_id": run_id,
        "scenario_names": [
            scenario_result.scenario_name
            for scenario_result in run_result.scenario_results
        ],
        "scenario_tags": scenario_tags,
        "artifacts": {
            name: str(path.relative_to(output_dir))
            for name, path in artifact_paths.items()
        },
    }


def _strip_timing_fields(value: Any) -> Any:
    """Recursively remove volatile timing fields from a payload."""

    if isinstance(value, dict):
        return {
            key: _strip_timing_fields(item)
            for key, item in value.items()
            if key not in _TIMING_FIELD_NAMES
        }
    if isinstance(value, list):
        return [_strip_timing_fields(item) for item in value]
    return value


def _select_summary_rows(
    summary: BenchmarkExperimentSummary | None,
    *,
    group_type: str,
    metric_group: str,
) -> list[Any]:
    """Select deterministic summary rows for one Markdown section.

    Args:
        summary: Optional grouped summary to filter.
        group_type: Summary grouping family to keep.
        metric_group: Metric family to keep.

    Returns:
        Matching summary rows.
    """

    if summary is None:
        return []
    return [
        row
        for row in summary.summary_rows
        if row.group_type == group_type and row.metric_group == metric_group
    ]


def _append_summary_section(lines: list[str], *, title: str, rows: list[Any]) -> None:
    """Append one grouped-summary Markdown section when rows exist.

    Args:
        lines: Markdown lines being accumulated.
        title: Section heading.
        rows: Summary rows to render.

    Returns:
        None.
    """

    if not rows:
        return
    lines.append(f"## {title}")
    lines.append("")
    lines.append("| Group | Metric | Mean | Median | Std | Min | Max | Q1 | Q3 | IQR | Tags |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        stats = row.statistics
        display_group = row.group_label
        lines.append(
            "| "
            f"{display_group} | "
            f"{row.metric_name} | "
            f"{stats.mean:.3f} | "
            f"{stats.median:.3f} | "
            f"{stats.standard_deviation:.3f} | "
            f"{stats.minimum:.3f} | "
            f"{stats.maximum:.3f} | "
            f"{stats.q1:.3f} | "
            f"{stats.q3:.3f} | "
            f"{stats.iqr:.3f} | "
            f"{', '.join(row.tags) or '-'} |"
        )
    lines.append("")
