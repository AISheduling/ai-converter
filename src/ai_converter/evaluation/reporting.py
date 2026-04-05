"""Reporting helpers for canonical, telemetry, and Markdown benchmark outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .benchmark import BenchmarkRunResult

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


def _build_canonical_benchmark_payload(result: BenchmarkRunResult) -> dict[str, Any]:
    """Build the canonical machine-readable benchmark payload."""

    return _strip_timing_fields(result.model_dump(mode="python"))


def _build_benchmark_telemetry_payload(result: BenchmarkRunResult) -> dict[str, Any]:
    """Build a timing-only telemetry payload for optional sidecar export."""

    return {
        "scenario_results": [
            {
                "scenario_name": scenario_result.scenario_name,
                "subject_results": [
                    {
                        "subject_name": subject_result.subject_name,
                        "subject_kind": subject_result.subject_kind,
                        "preparation_seconds": subject_result.preparation_seconds,
                        "runtime_seconds": subject_result.metrics.runtime_seconds,
                        "case_results": [
                            {
                                "name": case_result.name,
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
