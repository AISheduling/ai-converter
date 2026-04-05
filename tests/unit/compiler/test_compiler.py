"""Focused unit tests for MappingIR compilation and runtime helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_converter.compiler import CompilationError, ConverterPackage, compile_mapping_ir
from ai_converter.compiler.runtime_ops import (
    UnsafeExpressionError,
    cast_value,
    derive_value,
    map_enum_value,
    unit_convert_value,
)
from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment


def test_compiler_emits_importable_module() -> None:
    """Verify that the compiler emits deterministic, importable Python modules.

    Returns:
        None.
    """

    first = compile_mapping_ir(_program(), module_name="compiled_demo_one")
    second = compile_mapping_ir(_program(), module_name="compiled_demo_two")

    assert isinstance(first, ConverterPackage)
    assert callable(first.module.convert)
    assert "def convert(record):" in first.source_code
    assert "from ai_converter.compiler import runtime_ops" in first.source_code
    assert "from llm_converter.compiler import runtime_ops" not in first.source_code
    assert first.source_code == second.source_code
    assert first.manifest.source_sha256 == second.manifest.source_sha256


def test_compiled_converter_executes_without_llm() -> None:
    """Verify that the compiled converter runs deterministically without LLM usage.

    Returns:
        None.
    """

    converter = compile_mapping_ir(_program(), module_name="compiled_demo_exec")

    output = converter.convert(
        {
            "task_id": "T-1",
            "task_name": None,
            "status_text": "READY",
            "duration_hours": 1.5,
            "tags": ["ops", "backend"],
            "owner": {"email": "ops@example.com"},
        }
    )

    assert output == {
        "task": {
            "id": "T-1",
            "name": "Unnamed",
        },
        "status": "ready",
        "duration_minutes": 90.0,
        "metadata": {
            "tags": "ops,backend",
            "owner_email": "ops@example.com",
            "summary": "Unnamed@T-1",
        },
    }


def test_converter_package_manifest_is_versioned_and_machine_readable() -> None:
    """Verify that compiled packages expose a versioned manifest payload.

    Returns:
        None.
    """

    package = compile_mapping_ir(_program(), module_name="compiled_demo_manifest")
    payload = package.to_manifest_payload()

    assert payload["artifact_kind"] == "ConverterPackage"
    assert payload["artifact_version"] == "1.0"
    assert payload["program_version"] == _program().version
    assert "ai_converter.validation.run_acceptance_suite" in payload["validation_entry_points"]
    assert "tests/unit/compiler/test_compiler.py" in payload["test_paths"]
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_compiler_rejects_duplicate_source_ref_ids_when_validation_is_disabled() -> None:
    """Verify that the compiler defends against duplicate source ids on bypass paths.

    Returns:
        None.
    """

    with pytest.raises(CompilationError, match="duplicate source_ref ids: 'src_task_id'"):
        compile_mapping_ir(
            _program_with_duplicate_source_ref_ids(),
            module_name="compiled_duplicate_source_ids",
            validate_program=False,
        )


def test_compiled_converter_fails_fast_on_hierarchical_target_conflict_when_validation_is_disabled() -> None:
    """Verify that bypass paths do not silently clobber parent target values.

    Returns:
        None.
    """

    converter = compile_mapping_ir(
        _program_with_hierarchical_target_conflict(),
        module_name="compiled_hierarchical_target_conflict",
        validate_program=False,
    )

    with pytest.raises(ValueError, match="existing parent value at 'task'"):
        converter.convert({"task_payload": "legacy", "task_id": "ID-2"})


def test_converter_package_export_is_deterministic() -> None:
    """Verify that package export writes deterministic manifest and payload files.

    Returns:
        None.
    """

    first = compile_mapping_ir(_program(), module_name="compiled_demo_export")
    second = compile_mapping_ir(_program(), module_name="compiled_demo_export")

    workspace_temp_root = Path.cwd() / ".pytest-local-tmp"
    workspace_temp_root.mkdir(exist_ok=True)
    try:
        first_export = first.export(workspace_temp_root / "export-first")
        second_export = second.export(workspace_temp_root / "export-second")

        assert first_export.manifest_path.read_text(
            encoding="utf-8"
        ) == second_export.manifest_path.read_text(encoding="utf-8")
        assert first_export.module_path.read_text(
            encoding="utf-8"
        ) == second_export.module_path.read_text(encoding="utf-8")
        assert first_export.program_path.read_text(
            encoding="utf-8"
        ) == second_export.program_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(workspace_temp_root, ignore_errors=True)


def test_runtime_cast_and_enum_mapping() -> None:
    """Verify that casting and enum mapping helpers behave deterministically.

    Returns:
        None.
    """

    assert cast_value("5", "int") == 5
    assert cast_value("true", "bool") is True
    assert map_enum_value("READY", {"READY": "ready"}) == "ready"


def test_runtime_unit_convert() -> None:
    """Verify that the runtime unit-conversion helper scales numeric values.

    Returns:
        None.
    """

    assert unit_convert_value(2, 60, from_unit="hours", to_unit="minutes") == 120
    assert unit_convert_value([1, 2], 60, from_unit="hours", to_unit="minutes") == [60, 120]


def test_safe_derive_rejects_disallowed_expressions() -> None:
    """Verify that unsafe derive expressions are rejected without ``eval``.

    Returns:
        None.
    """

    with pytest.raises(UnsafeExpressionError):
        derive_value("__import__('os').system('calc')", {"value": 1})


def _program() -> MappingIR:
    """Build a deterministic MappingIR program used by compiler tests.

    Returns:
        MappingIR program covering the key TASK-04 runtime helpers.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status_text", dtype="str"),
            SourceReference(id="src_duration_hours", path="duration_hours", dtype="float"),
            SourceReference(id="src_tags", path="tags", dtype="list"),
            SourceReference(id="src_owner", path="owner", dtype="dict"),
        ],
        steps=[
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(
                id="default_task_name",
                operation=StepOperation(kind="default", source_ref="src_task_name", value="Unnamed"),
            ),
            MappingStep(
                id="map_status",
                operation=StepOperation(kind="map_enum", source_ref="src_status", mapping={"READY": "ready"}),
            ),
            MappingStep(
                id="duration_minutes",
                operation=StepOperation(
                    kind="unit_convert",
                    source_ref="src_duration_hours",
                    factor=60.0,
                    from_unit="hours",
                    to_unit="minutes",
                ),
            ),
            MappingStep(
                id="merge_tags",
                operation=StepOperation(kind="merge", source_refs=["src_tags"], delimiter=","),
            ),
            MappingStep(
                id="owner_email",
                operation=StepOperation(kind="unnest", source_ref="src_owner", child_path="email"),
            ),
            MappingStep(
                id="summary",
                operation=StepOperation(
                    kind="derive",
                    step_refs=["default_task_name", "copy_task_id"],
                    expression="default_task_name + '@' + copy_task_id",
                ),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="default_task_name", target_path="task.name"),
            TargetAssignment(step_id="map_status", target_path="status"),
            TargetAssignment(step_id="duration_minutes", target_path="duration_minutes"),
            TargetAssignment(step_id="merge_tags", target_path="metadata.tags"),
            TargetAssignment(step_id="owner_email", target_path="metadata.owner_email"),
            TargetAssignment(step_id="summary", target_path="metadata.summary"),
        ],
    )


def _program_with_duplicate_source_ref_ids() -> MappingIR:
    """Build an invalid MappingIR program with duplicate source reference ids.

    Returns:
        Invalid MappingIR program whose duplicate ids would overwrite source values.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_id", path="task_name", dtype="str"),
        ],
        steps=[MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id"))],
        assignments=[TargetAssignment(step_id="copy_task_id", target_path="task.id")],
    )


def _program_with_hierarchical_target_conflict() -> MappingIR:
    """Build an invalid MappingIR program with parent and child writes.

    Returns:
        Invalid MappingIR program that bypass paths must reject at runtime.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_payload", path="task_payload", dtype="str"),
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
        ],
        steps=[
            MappingStep(id="copy_task_payload", operation=StepOperation(kind="copy", source_ref="src_task_payload")),
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_payload", target_path="task"),
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
        ],
    )
