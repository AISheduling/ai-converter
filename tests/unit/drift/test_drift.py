"""Focused unit tests for deterministic drift detection and patch adaptation."""

from __future__ import annotations

from pathlib import Path

from llm_converter.drift import (
    AddSourceAliasOperation,
    ConverterPatch,
    RetargetSourceRefOperation,
    apply_converter_patch,
    apply_mapping_ir_patch,
    classify_drift,
    propose_compatible_patch,
)
from llm_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from llm_converter.profiling import build_profile_report
from llm_converter.schema import SourceFieldSpec, SourceSchemaSpec

ROOT = Path(__file__).resolve().parents[3]
DRIFT_FIXTURES = ROOT / "tests" / "fixtures" / "drift"


def test_drift_classifier_detects_additive_change() -> None:
    """Verify that additive compatible drift is classified deterministically."""

    report = classify_drift(
        _profile("baseline_schedule.json"),
        _profile("additive_schedule.json"),
        baseline_schema=_source_schema(),
    )

    assert report.classification == "additive_compatible"
    assert any(
        field_drift.kind == "added" and field_drift.candidate_path == "task_priority"
        for field_drift in report.field_drifts
    )


def test_drift_classifier_detects_rename_change() -> None:
    """Verify that compatible renames are classified deterministically."""

    report = classify_drift(
        _profile("baseline_schedule.json"),
        _profile("rename_schedule.json"),
        baseline_schema=_source_schema(),
    )

    assert report.classification == "rename_compatible"
    assert any(
        field_drift.kind == "renamed"
        and field_drift.baseline_path == "task_name"
        and field_drift.candidate_path == "taskName"
        for field_drift in report.field_drifts
    )


def test_drift_classifier_detects_breaking_change() -> None:
    """Verify that unresolved required-field removal is breaking drift."""

    report = classify_drift(
        _profile("baseline_schedule.json"),
        _profile("breaking_schedule.json"),
        baseline_schema=_source_schema(),
    )

    assert report.classification == "breaking_change"
    assert any(
        field_drift.kind == "removed" and field_drift.baseline_path == "task_id"
        for field_drift in report.field_drifts
    )


def test_patch_apply_updates_mapping_ir_locally() -> None:
    """Verify that MappingIR patch application only updates targeted sections."""

    mapping_ir = _mapping_ir()
    patch = ConverterPatch(
        classification="rename_compatible",
        mapping_ir_operations=[
            RetargetSourceRefOperation(
                source_ref_id="src_task_name",
                new_path="taskName",
                reason="rename-compatible test patch",
            )
        ],
        audit_trail=[],
    )

    payload = patch.model_dump(mode="json")
    patched = apply_mapping_ir_patch(mapping_ir, patch)

    assert payload["mapping_ir_operations"][0]["kind"] == "retarget_source_ref"
    assert patched.source_refs[1].path == "taskName"
    assert patched.source_refs[0].path == mapping_ir.source_refs[0].path
    assert patched.assignments == mapping_ir.assignments
    assert patched.steps == mapping_ir.steps


def test_heuristics_resolve_safe_rename_without_llm() -> None:
    """Verify that compatible rename drift resolves without live LLM calls."""

    baseline_schema = _source_schema()
    mapping_ir = _mapping_ir()
    drift_report = classify_drift(
        _profile("baseline_schedule.json"),
        _profile("rename_schedule.json"),
        baseline_schema=baseline_schema,
    )

    resolution = propose_compatible_patch(drift_report, baseline_schema, mapping_ir)

    assert resolution.compatible is True
    assert resolution.patch is not None
    assert any(decision.kind == "rename_alignment" for decision in resolution.decisions)
    assert any(
        isinstance(operation, AddSourceAliasOperation)
        and operation.path == "task_name"
        and operation.alias == "taskName"
        for operation in resolution.patch.source_schema_operations
    )
    assert any(
        isinstance(operation, RetargetSourceRefOperation)
        and operation.source_ref_id == "src_task_name"
        and operation.new_path == "taskName"
        for operation in resolution.patch.mapping_ir_operations
    )

    patched_schema, patched_mapping = apply_converter_patch(
        baseline_schema,
        mapping_ir,
        resolution.patch,
    )

    task_name_field = next(field for field in patched_schema.fields if field.path == "task_name")
    assert "taskName" in task_name_field.aliases
    assert patched_mapping.source_refs[1].path == "taskName"


def _profile(filename: str):
    """Build one deterministic profile report from a drift fixture.

    Args:
        filename: Fixture filename under ``tests/fixtures/drift``.

    Returns:
        Profile report for the requested fixture.
    """

    return build_profile_report(DRIFT_FIXTURES / filename, sample_limit=2)


def _source_schema() -> SourceSchemaSpec:
    """Build the deterministic source schema contract for drift tests.

    Returns:
        Source schema used across the focused drift tests.
    """

    return SourceSchemaSpec(
        source_name="schedule",
        source_format="json",
        root_type="list",
        fields=[
            SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str"),
            SourceFieldSpec(path="task_name", semantic_name="task_name", dtype="str"),
            SourceFieldSpec(path="status_text", semantic_name="status_text", dtype="str"),
        ],
    )


def _mapping_ir() -> MappingIR:
    """Build the deterministic MappingIR program used by drift tests.

    Returns:
        MappingIR program that consumes the focused schedule schema.
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
                operation=StepOperation(
                    kind="map_enum",
                    source_ref="src_status",
                    mapping={"READY": "ready", "DONE": "done"},
                ),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
            TargetAssignment(step_id="map_status", target_path="status"),
        ],
    )
