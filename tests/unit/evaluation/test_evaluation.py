"""Focused unit tests for benchmark metrics, harness execution, and reporting."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from ai_converter.compiler import compile_mapping_ir
from ai_converter.evaluation import (
    BenchmarkCase,
    BenchmarkScenario,
    BenchmarkStageArtifacts,
    BenchmarkSubject,
    build_synthetic_benchmark_scenario,
    compute_case_accuracy,
    compute_macro_micro_accuracy,
    compute_required_field_accuracy,
    export_benchmark_experiment_reports,
    export_benchmark_reports,
    run_benchmark,
    run_repeated_benchmark,
)
from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.synthetic_benchmark import BundleStore, DriftSpec, L0TemplateSpec, ScenarioSamplerConfig, sample_canonical_scenario
from ai_converter.validation import SemanticAssertion

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "drift"
RAW_ROOT = ROOT / ".agent" / "tasks" / "TASK-Bench-04" / "raw"


class DemoTask(BaseModel):
    """Target task model used by evaluation tests."""

    id: str
    name: str


class DemoTarget(BaseModel):
    """Target root model used by evaluation tests."""

    task: DemoTask
    status: str


class SyntheticTask(BaseModel):
    """Synthetic benchmark task model used by evaluation tests."""

    id: str
    name: str
    status: str
    duration_days: int
    assignee: str | None = None
    tags: list[str]


class SyntheticTarget(BaseModel):
    """Synthetic benchmark target payload used by evaluation tests."""

    tasks: list[SyntheticTask]


def _build_demo_scenario() -> BenchmarkScenario:
    """Build the deterministic demo scenario shared by several tests."""

    return BenchmarkScenario(
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


def _build_demo_benchmark_result():
    """Build a deterministic benchmark result for reporting tests."""

    subject = BenchmarkSubject.from_converter(
        "baseline",
        lambda record: {
            "task": {"id": record["task_id"], "name": record["task_name"]},
            "status": record["status_text"].lower(),
        },
    )
    return run_benchmark([subject], [_build_demo_scenario()])


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

    result = run_benchmark([subject], [_build_demo_scenario()])
    subject_result = result.scenario_results[0].subject_results[0]

    assert subject_result.subject_name == "fake-compiled"
    assert subject_result.metrics.pass_at_1 == 1.0
    assert subject_result.acceptance_report is not None
    assert subject_result.acceptance_report.coverage == 1.0
    assert subject_result.case_results[0].structural_validity is True
    assert subject_result.case_results[0].semantic_validity is True


def test_existing_run_benchmark_handles_base_and_drift_scenarios() -> None:
    """Verify that synthetic base and drift bundles reuse the existing harness."""

    base_bundle, drift_bundle = _build_synthetic_bundles()
    subject = BenchmarkSubject.from_converter(
        "synthetic-compiled",
        _convert_synthetic_payload,
        kind="compiled",
    )
    scenarios = [
        build_synthetic_benchmark_scenario(
            "synthetic-base",
            [base_bundle],
            target_model=SyntheticTarget,
            required_fields=["tasks"],
        ),
        build_synthetic_benchmark_scenario(
            "synthetic-drift",
            [drift_bundle],
            target_model=SyntheticTarget,
            required_fields=["tasks"],
        ),
    ]

    result = run_benchmark([subject], scenarios)
    base_result = result.scenario_results[0]
    drift_result = result.scenario_results[1]

    assert "synthetic" in base_result.tags
    assert "base" in base_result.tags
    assert "drift" in drift_result.tags
    assert "severity:low" in drift_result.tags
    assert "compatibility:rename_compatible" in drift_result.tags
    assert drift_result.subject_results[0].metrics.pass_at_1 == 1.0
    assert drift_result.subject_results[0].case_results[0].name == drift_bundle.metadata.bundle_id


def test_repeated_runs_are_grouped_without_forking_a_second_harness() -> None:
    """Verify that repeated runs wrap normal benchmark runs without replacing them."""

    subject = BenchmarkSubject.from_converter(
        "baseline",
        lambda record: {
            "task": {"id": record["task_id"], "name": record["task_name"]},
            "status": record["status_text"].lower(),
        },
    )
    scenario = _build_demo_scenario()

    repeated = run_repeated_benchmark(
        [subject],
        [scenario],
        run_count=2,
        experiment_name="demo-experiment",
    )
    direct = run_benchmark([subject], [scenario])

    assert repeated.experiment_name == "demo-experiment"
    assert [run.run_id for run in repeated.runs] == ["run-001", "run-002"]
    assert repeated.runs[0].result.model_dump(mode="json") == direct.model_dump(mode="json")
    assert repeated.runs[1].result.model_dump(mode="json") == direct.model_dump(mode="json")


def test_stage_artifacts_are_optional_but_supported() -> None:
    """Verify that optional stage metrics are preserved without a second model stack."""

    subject = BenchmarkSubject.from_converter(
        "fake-compiled",
        lambda record: {
            "task": {"id": record["task_id"], "name": record["task_name"]},
            "status": record["status_text"].lower(),
        },
        kind="compiled",
        stage_artifacts=BenchmarkStageArtifacts(
            source_structure_recovery=1.0,
            mapping_quality=0.75,
            artifacts={"trace_kind": "offline"},
        ),
    )

    result = run_benchmark([subject], [_build_demo_scenario()])
    stage_metrics = result.scenario_results[0].subject_results[0].metrics.stage_metrics

    assert stage_metrics is not None
    assert stage_metrics.build_success is True
    assert stage_metrics.execution_success_rate == 1.0
    assert stage_metrics.runtime_validity_rate == 1.0
    assert stage_metrics.structural_validity_rate == 1.0
    assert stage_metrics.semantic_validity_rate == 1.0
    assert stage_metrics.source_structure_recovery == 1.0
    assert stage_metrics.mapping_quality == 0.75
    assert stage_metrics.artifacts["trace_kind"] == "offline"


def test_converter_package_subject_reuses_existing_harness() -> None:
    """Verify that converter packages adapt cleanly into BenchmarkSubject."""

    package = compile_mapping_ir(
        MappingIR(
            source_refs=[
                SourceReference(id="src_task_id", path="task_id", dtype="str"),
                SourceReference(id="src_task_name", path="task_name", dtype="str"),
                SourceReference(id="src_status_text", path="status_text", dtype="str"),
            ],
            steps=[
                MappingStep(
                    id="copy_task_id",
                    operation=StepOperation(kind="copy", source_ref="src_task_id"),
                ),
                MappingStep(
                    id="copy_task_name",
                    operation=StepOperation(kind="copy", source_ref="src_task_name"),
                ),
                MappingStep(
                    id="map_status",
                    operation=StepOperation(
                        kind="map_enum",
                        source_ref="src_status_text",
                        mapping={"READY": "ready"},
                    ),
                ),
            ],
            assignments=[
                TargetAssignment(step_id="copy_task_id", target_path="task.id"),
                TargetAssignment(step_id="copy_task_name", target_path="task.name"),
                TargetAssignment(step_id="map_status", target_path="status"),
            ],
        ),
        module_name="evaluation_package_subject",
    )
    subject = BenchmarkSubject.from_converter_package("package-subject", package)

    result = run_benchmark([subject], [_build_demo_scenario()])
    subject_result = result.scenario_results[0].subject_results[0]

    assert subject_result.subject_kind == "compiled"
    assert subject_result.metrics.pass_at_1 == 1.0


def test_reporting_exports_machine_readable_and_md_outputs() -> None:
    """Verify that benchmark reporting exports JSON, CSV, and Markdown artifacts."""

    result = _build_demo_benchmark_result()

    output_dir = RAW_ROOT / "reporting-test-output"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = export_benchmark_reports(
            result,
            output_dir,
            stem="task_bench_04",
            include_telemetry=True,
        )

        json_payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert json_payload["scenario_results"][0]["scenario_name"] == "happy-path"
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
        assert "happy-path" in markdown
        assert "baseline" in markdown
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_repeated_run_exports_use_grouped_layout_and_per_run_artifacts() -> None:
    """Verify that repeated benchmark exports keep per-run artifacts deterministic."""

    base_bundle, drift_bundle = _build_synthetic_bundles()
    subject = BenchmarkSubject.from_converter(
        "synthetic-compiled",
        _convert_synthetic_payload,
        kind="compiled",
    )
    scenario = build_synthetic_benchmark_scenario(
        "synthetic-suite",
        [base_bundle, drift_bundle],
        target_model=SyntheticTarget,
        required_fields=["tasks"],
    )
    repeated = run_repeated_benchmark(
        [subject],
        [scenario],
        run_count=2,
        experiment_name="synthetic-suite",
    )

    output_dir = RAW_ROOT / "repeated-reporting-test-output"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = export_benchmark_experiment_reports(
            repeated,
            output_dir,
            stem="synthetic_benchmark",
            include_telemetry=True,
        )

        manifest = json.loads(paths["experiment_json"].read_text(encoding="utf-8"))
        assert manifest["experiment_name"] == "synthetic-suite"
        assert manifest["run_count"] == 2
        assert manifest["runs"][0]["run_id"] == "run-001"
        assert manifest["runs"][0]["artifacts"]["json"] == "runs\\run-001\\synthetic_benchmark.json"
        assert "synthetic" in manifest["runs"][0]["scenario_tags"]

        first_json = (output_dir / "runs" / "run-001" / "synthetic_benchmark.json").read_text(encoding="utf-8")
        second_json = (output_dir / "runs" / "run-002" / "synthetic_benchmark.json").read_text(encoding="utf-8")
        assert first_json == second_json
        _assert_timing_fields_absent(json.loads(first_json))

        first_telemetry = output_dir / "runs" / "run-001" / "synthetic_benchmark.telemetry.json"
        assert first_telemetry.exists()

        markdown = paths["experiment_markdown"].read_text(encoding="utf-8")
        assert "# Benchmark Experiment Summary" in markdown
        assert "synthetic-suite" in markdown
        assert "run-001" in markdown
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_canonical_benchmark_exports_are_reproducible_between_runs() -> None:
    """Verify that canonical machine-readable benchmark exports are reproducible."""

    first_result = _build_demo_benchmark_result()
    second_result = _build_demo_benchmark_result()

    output_dir = RAW_ROOT / "reporting-repro-output"
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


def _build_synthetic_bundles() -> tuple[object, object]:
    """Build deterministic base and drift bundles shared by synthetic benchmark tests."""

    sampled = sample_canonical_scenario(
        7,
        ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True),
    )
    store = BundleStore()
    base_bundle = store.build_bundle(
        sampled,
        L0TemplateSpec(),
        dataset_id="synthetic-demo",
        bundle_id="bundle-base",
        created_at="2026-04-06T00:00:00+00:00",
    )
    drift_bundle = store.build_drift_bundle(
        base_bundle,
        DriftSpec.model_validate_json((FIXTURE_ROOT / "rename_status_spec.json").read_text(encoding="utf-8")),
        bundle_id="bundle-drift",
        created_at="2026-04-06T00:00:00+00:00",
    )
    return base_bundle, drift_bundle


def _convert_synthetic_payload(record: dict[str, object]) -> dict[str, object]:
    """Convert a synthetic `L0` payload into the deterministic synthetic target."""

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
