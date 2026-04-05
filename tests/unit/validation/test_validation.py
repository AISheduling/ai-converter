"""Focused unit tests for structural, semantic, and repair-loop validation."""

from __future__ import annotations

from dataclasses import dataclass
import json

from pydantic import BaseModel, Field

from ai_converter.compiler import compile_mapping_ir
from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.validation import (
    AcceptanceCase,
    SemanticAssertion,
    run_acceptance_suite,
    run_bounded_repair_loop,
    validate_semantic_output,
    validate_structural_output,
)


class DemoTask(BaseModel):
    """Target task model used by TASK-04 validation tests."""

    id: str
    name: str


class DemoTarget(BaseModel):
    """Target root model used by TASK-04 validation tests."""

    task: DemoTask
    status: str = Field(description="Normalized task status")


def test_structural_validation_reports_missing_required_fields() -> None:
    """Verify that structural validation reports missing required fields.

    Returns:
        None.
    """

    result = validate_structural_output({"task": {"name": "Plan"}}, DemoTarget)

    assert result.valid is False
    assert any(issue.path == "task.id" for issue in result.issues)


def test_semantic_assertions_detect_wrong_mapping() -> None:
    """Verify that semantic assertions detect incorrect field mappings.

    Returns:
        None.
    """

    result = validate_semantic_output(
        {"task_id": "T-1", "task_name": "Plan"},
        {"task": {"id": "WRONG", "name": "Plan"}, "status": "ready"},
        [
            SemanticAssertion(
                name="task-id-equals-source",
                kind="equals",
                target_path="task.id",
                source_path="task_id",
            )
        ],
    )

    assert result.valid is False
    assert result.issues[0].assertion_name == "task-id-equals-source"


def test_acceptance_orchestrator_builds_report() -> None:
    """Verify that the acceptance suite returns a unified report.

    Returns:
        None.
    """

    converter = compile_mapping_ir(_valid_program(), module_name="acceptance_converter")
    dataset = [
        AcceptanceCase(
            name="happy-path",
            record={"task_id": "T-1", "task_name": "Plan", "status_text": "READY"},
            assertions=[
                SemanticAssertion(
                    name="task-id-equals-source",
                    kind="equals",
                    target_path="task.id",
                    source_path="task_id",
                ),
                SemanticAssertion(
                    name="enum-mapping",
                    kind="enum_mapping",
                    target_path="status",
                    source_path="status_text",
                    mapping={"READY": "ready"},
                ),
            ],
        )
    ]

    report = run_acceptance_suite(converter.convert, dataset, DemoTarget)

    assert report.execution_success is True
    assert report.structural_validity is True
    assert report.semantic_validity is True
    assert report.coverage == 1.0
    artifact = report.to_trace_artifact()
    assert artifact["artifact_kind"] == "acceptance_report_trace"
    assert artifact["artifact_version"] == "1.0"
    assert artifact["cases"][0]["name"] == "happy-path"
    assert json.loads(json.dumps(artifact)) == artifact


def test_bounded_repair_loop_stops_at_limit() -> None:
    """Verify that the repair loop stops at the configured iteration limit.

    Returns:
        None.
    """

    strategy = _NoOpRepairStrategy()
    result = run_bounded_repair_loop(
        _invalid_semantic_program(),
        _dataset(),
        DemoTarget,
        strategy,
        max_repair_iterations=1,
        module_name_prefix="repair_limit",
    )

    assert result.success is False
    assert result.iterations_used == 1
    assert len(result.history) == 2
    assert strategy.calls == 1
    assert result.final_decision == "max_iterations_reached"
    assert [trace.decision for trace in result.attempt_traces] == ["patched", "max_iterations_reached"]
    artifact = result.to_trace_artifact()
    assert artifact["artifact_kind"] == "repair_loop_trace"
    assert artifact["artifact_version"] == "1.0"
    assert artifact["attempt_traces"][0]["failure_bundle"]["attempt"] == 0
    assert artifact["attempt_traces"][0]["patched_program"] is not None
    assert artifact["attempt_traces"][1]["decision"] == "max_iterations_reached"
    assert json.loads(json.dumps(artifact)) == artifact


def test_bounded_repair_loop_succeeds_with_fake_patch_strategy() -> None:
    """Verify that the repair loop can succeed with a fake patch strategy.

    Returns:
        None.
    """

    strategy = _SinglePatchRepairStrategy()
    result = run_bounded_repair_loop(
        _invalid_semantic_program(),
        _dataset(),
        DemoTarget,
        strategy,
        max_repair_iterations=2,
        module_name_prefix="repair_success",
    )

    assert result.success is True
    assert result.iterations_used == 1
    assert result.final_report.coverage == 1.0
    assert strategy.calls == 1
    assert result.final_decision == "accepted"
    assert [trace.decision for trace in result.attempt_traces] == ["patched", "accepted"]
    assert result.to_trace_artifact()["attempt_traces"][1]["acceptance_report"]["coverage"] == 1.0


def test_bounded_repair_loop_records_strategy_decline() -> None:
    """Verify that the repair trace records when the strategy stops patching.

    Returns:
        None.
    """

    strategy = _DecliningRepairStrategy()
    result = run_bounded_repair_loop(
        _invalid_semantic_program(),
        _dataset(),
        DemoTarget,
        strategy,
        max_repair_iterations=2,
        module_name_prefix="repair_decline",
    )

    assert result.success is False
    assert result.final_decision == "strategy_declined"
    assert [trace.decision for trace in result.attempt_traces] == ["strategy_declined"]
    assert result.to_trace_artifact()["attempt_traces"][0]["failure_bundle"]["attempt"] == 0


def _dataset() -> list[AcceptanceCase]:
    """Build the deterministic acceptance dataset for repair-loop tests.

    Returns:
        List of acceptance cases used by the repair-loop tests.
    """

    return [
        AcceptanceCase(
            name="repairable-case",
            record={"task_id": "T-1", "task_name": "Plan", "status_text": "READY"},
            assertions=[
                SemanticAssertion(
                    name="task-id-equals-source",
                    kind="equals",
                    target_path="task.id",
                    source_path="task_id",
                ),
                SemanticAssertion(
                    name="enum-mapping",
                    kind="enum_mapping",
                    target_path="status",
                    source_path="status_text",
                    mapping={"READY": "ready"},
                ),
            ],
        )
    ]


def _valid_program() -> MappingIR:
    """Build a valid MappingIR program used by validation tests.

    Returns:
        Semantically correct MappingIR program.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status_text", dtype="str"),
        ],
        steps=[
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(
                id="map_status",
                operation=StepOperation(kind="map_enum", source_ref="src_status", mapping={"READY": "ready"}),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
            TargetAssignment(step_id="map_status", target_path="status"),
        ],
    )


def _invalid_semantic_program() -> MappingIR:
    """Build a semantically incorrect MappingIR program for repair-loop tests.

    Returns:
        Semantically incorrect MappingIR program.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status_text", dtype="str"),
        ],
        steps=[
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(
                id="map_status",
                operation=StepOperation(kind="map_enum", source_ref="src_status", mapping={"READY": "ready"}),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_name", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name", allow_overwrite=True),
            TargetAssignment(step_id="map_status", target_path="status"),
        ],
    )


@dataclass
class _NoOpRepairStrategy:
    """Repair strategy that never produces a successful patch."""

    calls: int = 0

    def propose_patch(self, program: MappingIR, failure_bundle) -> MappingIR:
        """Return the unchanged program to force loop termination at the limit.

        Args:
            program: Current failing MappingIR program.
            failure_bundle: Failure context for the current attempt.

        Returns:
            The unchanged program.
        """

        del failure_bundle
        self.calls += 1
        return program


@dataclass
class _SinglePatchRepairStrategy:
    """Repair strategy that swaps in a known-good program after one failure."""

    calls: int = 0

    def propose_patch(self, program: MappingIR, failure_bundle) -> MappingIR:
        """Return a valid replacement program after the first failure.

        Args:
            program: Current failing MappingIR program.
            failure_bundle: Failure context for the current attempt.

        Returns:
            A repaired MappingIR program.
        """

        del program, failure_bundle
        self.calls += 1
        return _valid_program()


@dataclass
class _DecliningRepairStrategy:
    """Repair strategy that explicitly stops after the first failure."""

    calls: int = 0

    def propose_patch(self, program: MappingIR, failure_bundle) -> MappingIR | None:
        """Decline to produce a patch for the current failure.

        Args:
            program: Current failing MappingIR program.
            failure_bundle: Failure context for the current attempt.

        Returns:
            ``None`` to stop the repair loop.
        """

        del program, failure_bundle
        self.calls += 1
        return None
