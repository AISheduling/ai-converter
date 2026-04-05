"""Smoke integration tests for the compiled converter pipeline."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ai_converter.compiler import compile_mapping_ir
from ai_converter.mapping_ir import MappingIR, MappingIRValidator, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.profiling import build_profile_report
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec, build_target_schema_card
from ai_converter.validation import validate_structural_output


ROOT = Path(__file__).resolve().parents[3]
PROFILE_FIXTURES = ROOT / "tests" / "fixtures" / "profiling"


class ScheduleSummary(BaseModel):
    """Simple integration target model for the TASK-04 smoke test."""

    project_name: str
    priority: int
    first_task_id: str
    label: str


def test_converter_pipeline_smoke_profile_to_validation() -> None:
    """Verify the end-to-end offline path from profile to compiled validation.

    Returns:
        None.
    """

    report = build_profile_report(PROFILE_FIXTURES / "sample_schedule.json", sample_limit=1)
    source_schema = SourceSchemaSpec(
        source_name="sample_schedule",
        source_format="json",
        root_type="list",
        schema_fingerprint=report.schema_fingerprint,
        fields=[
            SourceFieldSpec(path="project.name", semantic_name="project_name", dtype="str"),
            SourceFieldSpec(path="metadata.priority", semantic_name="priority", dtype="int"),
            SourceFieldSpec(path="tasks", semantic_name="tasks", dtype="list"),
        ],
    )
    target_schema = build_target_schema_card(ScheduleSummary)
    program = MappingIR(
        source_refs=[
            SourceReference(id="src_project_name", path="project.name", dtype="str"),
            SourceReference(id="src_priority", path="metadata.priority", dtype="int"),
            SourceReference(id="src_tasks", path="tasks", dtype="list"),
        ],
        steps=[
            MappingStep(id="copy_project_name", operation=StepOperation(kind="copy", source_ref="src_project_name")),
            MappingStep(id="copy_priority", operation=StepOperation(kind="copy", source_ref="src_priority")),
            MappingStep(
                id="first_task_id",
                operation=StepOperation(kind="unnest", source_ref="src_tasks", child_path="0.id"),
            ),
            MappingStep(
                id="label",
                operation=StepOperation(
                    kind="derive",
                    step_refs=["copy_project_name", "first_task_id"],
                    expression="copy_project_name + '-' + first_task_id",
                ),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_project_name", target_path="project_name"),
            TargetAssignment(step_id="copy_priority", target_path="priority"),
            TargetAssignment(step_id="first_task_id", target_path="first_task_id"),
            TargetAssignment(step_id="label", target_path="label"),
        ],
    )

    validation = MappingIRValidator().validate(
        program,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    assert validation.valid is True

    compiled = compile_mapping_ir(program, module_name="integration_schedule_summary")
    converted = compiled.convert(
        {
            "project": {"name": "Alpha"},
            "tasks": [{"id": "A-01", "duration": 5}],
            "metadata": {"priority": 1},
        }
    )
    structural = validate_structural_output(converted, ScheduleSummary)

    assert compiled.manifest.artifact_kind == "ConverterPackage"
    assert structural.valid is True
    assert converted["label"] == "Alpha-A-01"
