"""Smoke coverage for the offline synthetic benchmark reporting workflow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from ai_converter.evaluation import (
    BenchmarkStageArtifacts,
    BenchmarkSubject,
    build_synthetic_benchmark_scenario,
    export_benchmark_experiment_reports,
    run_repeated_benchmark,
)
from ai_converter.synthetic_benchmark import (
    BundleStore,
    DriftSpec,
    L0TemplateSpec,
    ScenarioSamplerConfig,
    sample_canonical_scenario,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "drift"


class SyntheticSmokeTask(BaseModel):
    """Synthetic benchmark smoke-test task model."""

    id: str
    name: str
    status: str | None = None
    duration_days: int
    assignee: str | None = None
    tags: list[str]


class SyntheticSmokeTarget(BaseModel):
    """Synthetic benchmark smoke-test target payload."""

    tasks: list[SyntheticSmokeTask]


def test_e2e_smoke_pipeline_finishes_successfully() -> None:
    """Verify that the synthetic benchmark workflow stays runnable offline.

    Returns:
        None.
    """

    sampled = sample_canonical_scenario(
        11,
        ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True),
    )
    store = BundleStore()
    base_bundle = store.build_bundle(
        sampled,
        L0TemplateSpec(),
        dataset_id="synthetic-smoke",
        bundle_id="bundle-base",
        created_at="2026-04-06T00:00:00+00:00",
    )
    rename_bundle = store.build_drift_bundle(
        base_bundle,
        DriftSpec.model_validate_json((FIXTURE_ROOT / "rename_status_spec.json").read_text(encoding="utf-8")),
        bundle_id="bundle-drift-rename",
        created_at="2026-04-06T00:00:00+00:00",
    )
    nesting_bundle = store.build_drift_bundle(
        base_bundle,
        DriftSpec.model_validate_json((FIXTURE_ROOT / "high_nesting_spec.json").read_text(encoding="utf-8")),
        bundle_id="bundle-drift-nesting",
        created_at="2026-04-06T00:00:00+00:00",
    )

    subject = BenchmarkSubject.from_converter(
        "synthetic-compiled",
        _convert_synthetic_payload,
        kind="compiled",
        stage_artifacts=BenchmarkStageArtifacts(
            source_structure_recovery=1.0,
            mapping_quality=0.75,
            artifacts={"trace_kind": "offline-smoke"},
        ),
    )
    scenarios = [
        build_synthetic_benchmark_scenario(
            "synthetic-base",
            [base_bundle],
            target_model=SyntheticSmokeTarget,
            required_fields=["tasks"],
        ),
        build_synthetic_benchmark_scenario(
            "synthetic-drift-rename",
            [rename_bundle],
            target_model=SyntheticSmokeTarget,
            required_fields=["tasks"],
        ),
        build_synthetic_benchmark_scenario(
            "synthetic-drift-nesting",
            [nesting_bundle],
            target_model=SyntheticSmokeTarget,
            required_fields=["tasks"],
        ),
    ]
    repeated = run_repeated_benchmark(
        [subject],
        scenarios,
        run_count=2,
        experiment_name="synthetic-smoke",
    )

    output_dir = ROOT / ".pytest-local-tmp" / "synthetic-benchmark-workflow"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = export_benchmark_experiment_reports(
            repeated,
            output_dir,
            stem="synthetic_smoke",
            include_telemetry=True,
        )

        manifest = json.loads(paths["experiment_json"].read_text(encoding="utf-8"))
        summary_payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
        telemetry_payload = json.loads(paths["telemetry_summary_json"].read_text(encoding="utf-8"))
        markdown = paths["experiment_markdown"].read_text(encoding="utf-8")

        assert manifest["experiment_name"] == "synthetic-smoke"
        assert manifest["run_count"] == 2
        assert manifest["summary_artifacts"]["boxplot_csv"] == "synthetic_smoke.boxplot.csv"
        assert manifest["telemetry_artifacts"]["boxplot_csv"] == "synthetic_smoke.telemetry.boxplot.csv"
        assert summary_payload["run_count"] == 2
        assert telemetry_payload["run_count"] == 2
        assert any(
            row["group_type"] == "bundle_kind_subject" and row["bundle_kind"] == "base"
            for row in summary_payload["summary_rows"]
        )
        assert any(
            row["group_type"] == "bundle_kind_subject" and row["bundle_kind"] == "drift"
            for row in summary_payload["summary_rows"]
        )
        assert any(
            row["group_type"] == "compatibility_class_subject"
            and row["compatibility_class"] == "rename_compatible"
            for row in summary_payload["summary_rows"]
        )
        assert any(
            row["group_type"] == "compatibility_class_subject"
            and row["compatibility_class"] == "breaking_change"
            for row in summary_payload["summary_rows"]
        )
        assert any(
            row["metric_name"] == "runtime_seconds" and row["metric_group"] == "telemetry"
            for row in telemetry_payload["summary_rows"]
        )
        assert (output_dir / "runs" / "run-001" / "synthetic_smoke.json").exists()
        assert (output_dir / "runs" / "run-002" / "synthetic_smoke.telemetry.json").exists()
        assert "## Base vs Drift Comparison" in markdown
        assert "## Timing Summary" in markdown
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _convert_synthetic_payload(record: dict[str, object]) -> dict[str, object]:
    """Convert one deterministic synthetic `L0` payload into target rows.

    Args:
        record: Source-side `L0` payload rendered from a synthetic bundle.

    Returns:
        Converted target payload used by the smoke benchmark.
    """

    rows = record["records"]
    assert isinstance(rows, list)
    tasks: list[dict[str, object]] = []
    for row in rows:
        assert isinstance(row, dict)
        tasks.append(
            {
                "id": row["task_id"],
                "name": row["task_name"],
                "status": row.get("status_text", row.get("status_text_label")),
                "duration_days": row["duration_days"],
                "assignee": row.get("assignee"),
                "tags": list(row.get("tags", [])),
            }
        )
    return {"tasks": tasks}
