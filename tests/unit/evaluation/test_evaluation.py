"""Focused unit tests for benchmark metrics, harness execution, and reporting."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from ai_converter.evaluation import (
    BenchmarkCase,
    BenchmarkRunResult,
    BenchmarkScenario,
    BenchmarkSubject,
    compute_case_accuracy,
    compute_macro_micro_accuracy,
    compute_required_field_accuracy,
    export_benchmark_reports,
    run_benchmark,
)
from ai_converter.validation import SemanticAssertion


class DemoTask(BaseModel):
    """Target task model used by evaluation tests."""

    id: str
    name: str


class DemoTarget(BaseModel):
    """Target root model used by evaluation tests."""

    task: DemoTask
    status: str


def _build_demo_benchmark_result() -> BenchmarkRunResult:
    """Build a deterministic benchmark result for reporting tests."""

    subject = BenchmarkSubject.from_converter(
        "baseline",
        lambda record: {
            "task": {"id": record["task_id"], "name": record["task_name"]},
            "status": record["status_text"].lower(),
        },
    )
    scenario = BenchmarkScenario(
        name="reporting-demo",
        target_model=DemoTarget,
        cases=[
            BenchmarkCase(
                name="case-1",
                record={"task_id": "T-1", "task_name": "Plan", "status_text": "READY"},
                expected_output={"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
                required_fields=["task.id", "status"],
                assertions=[
                    SemanticAssertion(
                        name="task-id-equals-source",
                        kind="equals",
                        target_path="task.id",
                        source_path="task_id",
                    )
                ],
            )
        ],
    )
    return run_benchmark([subject], [scenario])


def _assert_timing_fields_absent(value: object) -> None:
    """Assert that a nested payload contains no canonical timing fields."""

    if isinstance(value, dict):
        assert "preparation_seconds" not in value
        assert "runtime_seconds" not in value
        for nested in value.values():
            _assert_timing_fields_absent(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _assert_timing_fields_absent(nested)


def test_metrics_compute_required_field_accuracy() -> None:
    """Verify that required-field accuracy aggregates deterministically."""

    case_metrics = [
        compute_case_accuracy(
            {"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
            {"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
            required_fields=["task.id", "status"],
        ),
        compute_case_accuracy(
            {"task": {"id": "T-2", "name": "Ship"}, "status": "done"},
            {"task": {"id": "WRONG", "name": "Ship"}, "status": "done"},
            required_fields=["task.id", "status"],
        ),
    ]

    assert compute_required_field_accuracy(case_metrics) == 0.75


def test_metrics_compute_macro_micro_accuracy() -> None:
    """Verify that macro and micro field accuracy use the expected formulas."""

    case_metrics = [
        compute_case_accuracy(
            {"task": {"id": "T-1", "name": "Plan"}},
            {"task": {"id": "T-1", "name": "WRONG"}},
        ),
        compute_case_accuracy(
            {"status": "done", "task": {"id": "T-2"}},
            {"status": "done", "task": {"id": "T-2"}},
        ),
    ]

    macro_accuracy, micro_accuracy = compute_macro_micro_accuracy(case_metrics)

    assert macro_accuracy == 0.75
    assert micro_accuracy == 0.75


def test_benchmark_harness_runs_on_fake_converters() -> None:
    """Verify that the benchmark harness executes fake converters reproducibly."""

    subject = BenchmarkSubject.from_converter(
        "fake-compiled",
        lambda record: {
            "task": {"id": record["task_id"], "name": record["task_name"]},
            "status": record["status_text"].lower(),
        },
        kind="compiled",
    )
    scenario = BenchmarkScenario(
        name="happy-path",
        target_model=DemoTarget,
        cases=[
            BenchmarkCase(
                name="case-1",
                record={"task_id": "T-1", "task_name": "Plan", "status_text": "READY"},
                expected_output={"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
                required_fields=["task.id", "status"],
                assertions=[
                    SemanticAssertion(
                        name="task-id-equals-source",
                        kind="equals",
                        target_path="task.id",
                        source_path="task_id",
                    ),
                    SemanticAssertion(
                        name="status-normalized",
                        kind="enum_mapping",
                        target_path="status",
                        source_path="status_text",
                        mapping={"READY": "ready"},
                    ),
                ],
            )
        ],
    )

    result = run_benchmark([subject], [scenario])
    subject_result = result.scenario_results[0].subject_results[0]

    assert subject_result.subject_name == "fake-compiled"
    assert subject_result.metrics.pass_at_1 == 1.0
    assert subject_result.acceptance_report is not None
    assert subject_result.acceptance_report.coverage == 1.0
    assert subject_result.case_results[0].structural_validity is True
    assert subject_result.case_results[0].semantic_validity is True


def test_reporting_exports_machine_readable_and_md_outputs() -> None:
    """Verify that benchmark reporting exports JSON, CSV, and Markdown artifacts."""

    result = _build_demo_benchmark_result()

    output_dir = Path(".agent") / "tasks" / "TASK-05" / "raw" / "reporting-test-output"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = export_benchmark_reports(
            result,
            output_dir,
            stem="task05",
            include_telemetry=True,
        )

        json_payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert json_payload["scenario_results"][0]["scenario_name"] == "reporting-demo"
        _assert_timing_fields_absent(json_payload)

        csv_text = paths["csv"].read_text(encoding="utf-8")
        assert "baseline" in csv_text
        assert "runtime_seconds" not in csv_text

        telemetry_payload = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
        assert telemetry_payload["scenario_results"][0]["subject_results"][0]["preparation_seconds"] >= 0.0
        assert telemetry_payload["scenario_results"][0]["subject_results"][0]["runtime_seconds"] >= 0.0
        assert telemetry_payload["scenario_results"][0]["subject_results"][0]["case_results"][0]["runtime_seconds"] >= 0.0

        markdown = paths["markdown"].read_text(encoding="utf-8")
        assert "# Benchmark Summary" in markdown
        assert "reporting-demo" in markdown
        assert "baseline" in markdown
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_canonical_benchmark_exports_are_reproducible_between_runs() -> None:
    """Verify that canonical machine-readable benchmark exports are reproducible."""

    first_result = _build_demo_benchmark_result()
    second_result = _build_demo_benchmark_result()

    output_dir = Path(".agent") / "tasks" / "TASK-05" / "raw" / "reporting-repro-output"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        first_paths = export_benchmark_reports(first_result, output_dir, stem="first")
        second_paths = export_benchmark_reports(second_result, output_dir, stem="second")

        first_json = first_paths["json"].read_text(encoding="utf-8")
        second_json = second_paths["json"].read_text(encoding="utf-8")
        first_csv = first_paths["csv"].read_text(encoding="utf-8")
        second_csv = second_paths["csv"].read_text(encoding="utf-8")

        assert first_json == second_json
        assert first_csv == second_csv
        _assert_timing_fields_absent(json.loads(first_json))
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
