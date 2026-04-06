"""Smoke test for the synthetic benchmark example runner."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SCRIPT = ROOT / "examples" / "synthetic_benchmark" / "run_example.py"


def test_synthetic_benchmark_example_runs_offline() -> None:
    """Verify that the synthetic benchmark example finishes offline."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "synthetic_benchmark_example"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    summary = module.run_example(output_dir=output_dir, run_count=2)
    experiment_manifest = json.loads(
        Path(summary["experiment_manifest_path"]).read_text(encoding="utf-8")
    )
    grouped_summary = json.loads(
        Path(summary["summary_json_path"]).read_text(encoding="utf-8")
    )
    telemetry_summary = json.loads(
        Path(summary["telemetry_summary_json_path"]).read_text(encoding="utf-8")
    )
    canonical_run = json.loads(
        (output_dir / "runs" / "run-001" / "synthetic_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    telemetry_run = json.loads(
        (output_dir / "runs" / "run-001" / "synthetic_benchmark.telemetry.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = Path(summary["experiment_markdown_path"]).read_text(encoding="utf-8")
    boxplot_csv = Path(summary["boxplot_csv_path"]).read_text(encoding="utf-8")

    assert summary["run_count"] == 2
    assert summary["experiment_name"] == "synthetic-benchmark-example"
    assert "synthetic-base" in summary["scenario_names"]
    assert "synthetic-drift-rename" in summary["scenario_names"]
    assert "synthetic-drift-nesting" in summary["scenario_names"]
    assert Path(summary["summary_path"]).exists()

    assert experiment_manifest["summary_artifacts"]["summary_json"] == "synthetic_benchmark.summary.json"
    assert experiment_manifest["telemetry_artifacts"]["summary_json"] == "synthetic_benchmark.telemetry.summary.json"
    assert grouped_summary["run_count"] == 2
    assert any(
        row["group_type"] == "drift_type_subject"
        and row["metric_name"] == "pass_at_1"
        for row in grouped_summary["summary_rows"]
    )
    assert any(
        row["metric_group"] == "telemetry"
        and row["metric_name"] == "runtime_seconds"
        for row in telemetry_summary["summary_rows"]
    )

    assert "preparation_seconds" not in json.dumps(canonical_run)
    assert "runtime_seconds" in json.dumps(telemetry_run)
    assert "## Scenario Summary" in markdown
    assert "## Base vs Drift Comparison" in markdown
    assert "## Timing Summary" in markdown
    assert "metric_group,metric_name,value" in boxplot_csv
    assert "drift_type" in boxplot_csv


def _load_example_module() -> ModuleType:
    """Load the synthetic benchmark example as an importable module.

    Returns:
        Loaded module for the example script.
    """

    spec = importlib.util.spec_from_file_location(
        "synthetic_benchmark_example",
        EXAMPLE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the synthetic benchmark example module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
