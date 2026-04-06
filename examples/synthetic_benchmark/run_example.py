"""Thin offline runner for the synthetic benchmark evaluation workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ai_converter.evaluation import (
    BenchmarkSubject,
    build_synthetic_benchmark_scenario,
    export_benchmark_experiment_reports,
    run_repeated_benchmark,
)
from ai_converter.synthetic_benchmark import BundleStore, DriftSpec, L0TemplateSpec, ScenarioSamplerConfig, sample_canonical_scenario


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "examples" / "synthetic_benchmark" / "generated"


class SyntheticTask(BaseModel):
    """Synthetic benchmark task model used by the example runner."""

    id: str
    name: str
    status: str
    duration_days: int
    assignee: str | None = None
    tags: list[str]


class SyntheticTarget(BaseModel):
    """Synthetic benchmark target payload used by the example runner."""

    tasks: list[SyntheticTask]


def run_example(
    *,
    output_dir: str | Path | None = None,
    run_count: int = 3,
) -> dict[str, Any]:
    """Run a small deterministic synthetic benchmark experiment.

    Args:
        output_dir: Directory where benchmark artifacts should be written.
        run_count: Number of repeated benchmark passes to execute.

    Returns:
        JSON-compatible summary of the generated experiment artifacts.
    """

    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    subject = BenchmarkSubject.from_converter(
        "synthetic-example",
        _convert_synthetic_payload,
        kind="compiled",
    )
    scenarios = _build_scenarios()
    experiment = run_repeated_benchmark(
        [subject],
        scenarios,
        run_count=run_count,
        experiment_name="synthetic-benchmark-example",
    )
    artifact_paths = export_benchmark_experiment_reports(
        experiment,
        resolved_output_dir,
        stem="synthetic_benchmark",
        include_telemetry=True,
    )

    summary = {
        "experiment_name": experiment.experiment_name,
        "run_count": len(experiment.runs),
        "scenario_names": [
            scenario.name
            for scenario in scenarios
        ],
        "output_dir": str(resolved_output_dir),
        "experiment_manifest_path": str(artifact_paths["experiment_json"]),
        "experiment_markdown_path": str(artifact_paths["experiment_markdown"]),
        "summary_json_path": str(artifact_paths["summary_json"]),
        "summary_csv_path": str(artifact_paths["summary_csv"]),
        "boxplot_csv_path": str(artifact_paths["boxplot_csv"]),
        "telemetry_summary_json_path": str(artifact_paths["telemetry_summary_json"]),
        "telemetry_summary_csv_path": str(artifact_paths["telemetry_summary_csv"]),
        "telemetry_boxplot_csv_path": str(artifact_paths["telemetry_boxplot_csv"]),
    }
    summary_path = resolved_output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["summary_path"] = str(summary_path)
    return summary


def main() -> int:
    """Run the synthetic benchmark example from the command line.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser(
        description="Run the offline synthetic benchmark example workflow.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where experiment artifacts should be written.",
    )
    parser.add_argument(
        "--run-count",
        type=int,
        default=3,
        help="Number of repeated benchmark runs to execute.",
    )
    args = parser.parse_args()
    summary = run_example(output_dir=args.output_dir, run_count=args.run_count)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _build_scenarios() -> list[Any]:
    """Build deterministic base and drift scenarios for the example.

    Returns:
        Benchmark scenarios reused by the example runner.
    """

    sampled = sample_canonical_scenario(
        11,
        ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True),
    )
    store = BundleStore()
    base_bundle = store.build_bundle(
        sampled,
        L0TemplateSpec(),
        dataset_id="synthetic-example",
        bundle_id="bundle-base",
        created_at="2026-04-06T00:00:00+00:00",
    )
    rename_bundle = store.build_drift_bundle(
        base_bundle,
        DriftSpec.model_validate(
            {
                "version": "1.0",
                "drift_id": "rename-status",
                "drift_type": "rename",
                "severity": "low",
                "compatibility_class": "rename_compatible",
                "operators": [
                    {
                        "kind": "rename_field",
                        "path": "status_text",
                        "new_path": "status_text_label",
                        "record_indexes": [0, 1, 2],
                    }
                ],
                "notes": [
                    "Rename the status field to a compatible source-side surface."
                ],
            }
        ),
        bundle_id="bundle-rename",
        created_at="2026-04-06T00:00:00+00:00",
    )
    nesting_bundle = store.build_drift_bundle(
        base_bundle,
        DriftSpec.model_validate(
            {
                "version": "1.0",
                "drift_id": "nest-status",
                "drift_type": "nesting",
                "severity": "high",
                "compatibility_class": "breaking_change",
                "operators": [
                    {
                        "kind": "nest_field",
                        "path": "status_text",
                        "new_path": "status.details",
                        "record_indexes": [0, 1, 2],
                    }
                ],
                "notes": [
                    "Move status into a nested object to force a structure-changing drift."
                ],
            }
        ),
        bundle_id="bundle-nesting",
        created_at="2026-04-06T00:00:00+00:00",
    )
    return [
        build_synthetic_benchmark_scenario(
            "synthetic-base",
            [base_bundle],
            target_model=SyntheticTarget,
            required_fields=["tasks"],
        ),
        build_synthetic_benchmark_scenario(
            "synthetic-drift-rename",
            [rename_bundle],
            target_model=SyntheticTarget,
            required_fields=["tasks"],
        ),
        build_synthetic_benchmark_scenario(
            "synthetic-drift-nesting",
            [nesting_bundle],
            target_model=SyntheticTarget,
            required_fields=["tasks"],
        ),
    ]


def _convert_synthetic_payload(record: dict[str, object]) -> dict[str, object]:
    """Convert a synthetic `L0` payload into the deterministic target shape.

    Args:
        record: Synthetic `L0` record to convert.

    Returns:
        Converted synthetic target payload.
    """

    rows = record["records"]
    assert isinstance(rows, list)
    tasks: list[dict[str, object]] = []
    for row in rows:
        assert isinstance(row, dict)
        status_value = row.get("status_text", row.get("status_text_label"))
        if status_value is None:
            nested_status = row.get("status")
            if isinstance(nested_status, dict):
                status_value = nested_status.get("details")
        tasks.append(
            {
                "id": row["task_id"],
                "name": row["task_name"],
                "status": status_value,
                "duration_days": row["duration_days"],
                "assignee": row.get("assignee"),
                "tags": list(row.get("tags", [])),
            }
        )
    return {"tasks": tasks}


if __name__ == "__main__":
    raise SystemExit(main())
