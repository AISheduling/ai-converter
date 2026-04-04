"""Reporting helpers for machine-readable and Markdown benchmark outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .benchmark import BenchmarkRunResult


def write_benchmark_json(result: BenchmarkRunResult, path: str | Path) -> Path:
    """Write one benchmark result bundle as formatted JSON.

    Args:
        result: Benchmark run result to serialize.
        path: Output path for the JSON artifact.

    Returns:
        The normalized output path.
    """

    output_path = Path(path)
    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_benchmark_csv(result: BenchmarkRunResult, path: str | Path) -> Path:
    """Write flattened per-case benchmark rows as CSV.

    Args:
        result: Benchmark run result to flatten.
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
                "runtime_seconds",
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
                            "runtime_seconds": round(case_result.runtime_seconds, 6),
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
) -> dict[str, Path]:
    """Write JSON, CSV, and Markdown benchmark artifacts into one directory.

    Args:
        result: Benchmark run result to export.
        output_dir: Directory where artifacts should be written.
        stem: Shared filename prefix for the generated artifacts.

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
    write_benchmark_json(result, paths["json"])
    write_benchmark_csv(result, paths["csv"])
    write_benchmark_markdown(result, paths["markdown"])
    return paths
