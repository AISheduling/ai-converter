"""Patch-application helpers for deterministic source and MappingIR updates."""

from __future__ import annotations

from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference
from ai_converter.schema import SourceSchemaSpec

from .models import (
    AddSourceAliasOperation,
    AddSourceFieldOperation,
    AddSourceReferenceOperation,
    ConverterPatch,
    ExtendEnumMappingOperation,
    PromoteStepToCastOperation,
    RetargetSourceRefOperation,
    UpdateSourceFieldOperation,
)


class PatchApplyError(ValueError):
    """Raised when a local converter patch cannot be applied safely."""


def apply_source_schema_patch(
    source_schema: SourceSchemaSpec,
    patch: ConverterPatch,
) -> SourceSchemaSpec:
    """Apply source-schema patch operations while preserving unaffected fields.

    Args:
        source_schema: Baseline source schema contract.
        patch: Local patch containing source-schema operations.

    Returns:
        A patched source schema contract.

    Raises:
        PatchApplyError: If the patch cannot be applied safely.
    """

    patched = source_schema.model_copy(deep=True)
    fields_by_path = {field.path: field for field in patched.fields}

    for operation in patch.source_schema_operations:
        if isinstance(operation, AddSourceFieldOperation):
            if operation.field.path in fields_by_path:
                raise PatchApplyError(
                    f"cannot add duplicate source field {operation.field.path!r}"
                )
            fields_by_path[operation.field.path] = operation.field.model_copy(deep=True)
            continue

        if isinstance(operation, AddSourceAliasOperation):
            field = fields_by_path.get(operation.path)
            if field is None:
                raise PatchApplyError(
                    f"cannot add alias to unknown source field {operation.path!r}"
                )
            aliases = sorted(set(field.aliases) | {operation.alias})
            fields_by_path[operation.path] = field.model_copy(update={"aliases": aliases})
            continue

        if isinstance(operation, UpdateSourceFieldOperation):
            field = fields_by_path.get(operation.path)
            if field is None:
                raise PatchApplyError(
                    f"cannot update unknown source field {operation.path!r}"
                )
            examples = list(field.examples)
            examples.extend(example for example in operation.append_examples if example not in examples)
            updates: dict[str, object] = {"examples": examples}
            if operation.dtype is not None:
                updates["dtype"] = operation.dtype
            if operation.nullable is not None:
                updates["nullable"] = operation.nullable
            if operation.cardinality is not None:
                updates["cardinality"] = operation.cardinality
            if operation.unit is not None:
                updates["unit"] = operation.unit
            fields_by_path[operation.path] = field.model_copy(update=updates)
            continue

        raise PatchApplyError(f"unsupported source-schema patch operation: {operation!r}")

    patched.fields = [fields_by_path[path] for path in sorted(fields_by_path)]
    return patched


def apply_mapping_ir_patch(
    mapping_ir: MappingIR,
    patch: ConverterPatch,
) -> MappingIR:
    """Apply MappingIR patch operations while preserving unrelated program parts.

    Args:
        mapping_ir: Baseline MappingIR program.
        patch: Local patch containing MappingIR operations.

    Returns:
        A patched MappingIR program.

    Raises:
        PatchApplyError: If the patch cannot be applied safely.
    """

    patched = mapping_ir.model_copy(deep=True)
    source_refs: dict[str, SourceReference] = {
        source_ref.id: source_ref for source_ref in patched.source_refs
    }
    steps: dict[str, MappingStep] = {step.id: step for step in patched.steps}
    original_source_refs: list[SourceReference] = list(mapping_ir.source_refs)
    original_steps: list[MappingStep] = list(mapping_ir.steps)

    for operation in patch.mapping_ir_operations:
        if isinstance(operation, RetargetSourceRefOperation):
            source_ref = source_refs.get(operation.source_ref_id)
            if source_ref is None:
                raise PatchApplyError(
                    f"cannot retarget unknown source ref {operation.source_ref_id!r}"
                )
            updates = {"path": operation.new_path}
            if operation.new_dtype is not None:
                updates["dtype"] = operation.new_dtype
            if operation.new_cardinality is not None:
                updates["cardinality"] = operation.new_cardinality
            source_refs[operation.source_ref_id] = source_ref.model_copy(update=updates)
            continue

        if isinstance(operation, AddSourceReferenceOperation):
            if operation.source_ref.id in source_refs:
                raise PatchApplyError(
                    f"cannot add duplicate source ref {operation.source_ref.id!r}"
                )
            source_refs[operation.source_ref.id] = operation.source_ref.model_copy(deep=True)
            continue

        if isinstance(operation, PromoteStepToCastOperation):
            step = steps.get(operation.step_id)
            if step is None:
                raise PatchApplyError(
                    f"cannot promote unknown MappingIR step {operation.step_id!r}"
                )
            if step.operation.kind not in {"copy", "rename", "cast"} or step.operation.source_ref is None:
                raise PatchApplyError(
                    f"step {operation.step_id!r} cannot be promoted to cast safely"
                )
            steps[operation.step_id] = _with_updated_step(
                step,
                kind="cast",
                to_type=operation.to_type,
            )
            continue

        if isinstance(operation, ExtendEnumMappingOperation):
            step = steps.get(operation.step_id)
            if step is None:
                raise PatchApplyError(
                    f"cannot extend enum mapping for unknown step {operation.step_id!r}"
                )
            if step.operation.kind != "map_enum":
                raise PatchApplyError(
                    f"step {operation.step_id!r} is not an enum-mapping step"
                )
            mapping = dict(step.operation.mapping)
            mapping.update(operation.mapping_updates)
            steps[operation.step_id] = _with_updated_step(step, mapping=mapping)
            continue

        raise PatchApplyError(f"unsupported MappingIR patch operation: {operation!r}")

    patched.source_refs = [
        source_refs[source_ref.id]
        for source_ref in original_source_refs
        if source_ref.id in source_refs
    ]
    for source_ref_id, source_ref in source_refs.items():
        if not any(existing.id == source_ref_id for existing in original_source_refs):
            patched.source_refs.append(source_ref)
    patched.steps = [steps[step.id] for step in original_steps]
    return patched


def apply_converter_patch(
    source_schema: SourceSchemaSpec,
    mapping_ir: MappingIR,
    patch: ConverterPatch,
) -> tuple[SourceSchemaSpec, MappingIR]:
    """Apply a local patch to both source-schema and MappingIR artifacts.

    Args:
        source_schema: Baseline source schema contract.
        mapping_ir: Baseline MappingIR program.
        patch: Local converter patch.

    Returns:
        Tuple of ``(patched_source_schema, patched_mapping_ir)``.
    """

    return (
        apply_source_schema_patch(source_schema, patch),
        apply_mapping_ir_patch(mapping_ir, patch),
    )


def _with_updated_step(step: MappingStep, **updates) -> MappingStep:
    """Return one MappingIR step with an updated operation payload.

    Args:
        step: MappingIR step to update.
        **updates: Operation field updates.

    Returns:
        A MappingIR step with the updated operation.
    """

    return step.model_copy(update={"operation": step.operation.model_copy(update=updates)})
