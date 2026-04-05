"""Deterministic heuristics for compatible drift resolution."""

from __future__ import annotations

from ai_converter.mapping_ir import MappingIR, SourceReference
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec

from .models import (
    AddSourceAliasOperation,
    AddSourceFieldOperation,
    AddSourceReferenceOperation,
    ConverterPatch,
    DriftReport,
    ExtendEnumMappingOperation,
    FieldSignature,
    HeuristicDecision,
    HeuristicResolution,
    PatchAuditEntry,
    PromoteStepToCastOperation,
    RetargetSourceRefOperation,
)


def propose_compatible_patch(
    drift_report: DriftReport,
    source_schema: SourceSchemaSpec,
    mapping_ir: MappingIR,
) -> HeuristicResolution:
    """Build a deterministic local patch for compatible drift cases.

    Args:
        drift_report: Drift report returned by the classifier.
        source_schema: Current source schema contract.
        mapping_ir: Current deterministic mapping program.

    Returns:
        A machine-readable heuristic resolution with an optional patch.
    """

    decisions: list[HeuristicDecision] = []
    source_operations = []
    mapping_operations = []
    audit_trail: list[PatchAuditEntry] = []
    unresolved_reasons: list[str] = []

    source_fields = {field.path: field for field in source_schema.fields}
    source_refs_by_path = {source_ref.path: source_ref for source_ref in mapping_ir.source_refs}

    for drift in drift_report.field_drifts:
        baseline_path = drift.baseline_path or ""
        candidate_path = drift.candidate_path or ""

        if drift.kind == "renamed" and baseline_path and candidate_path:
            field = source_fields.get(baseline_path)
            if field is None:
                reason = f"Cannot align rename for unknown source schema path {baseline_path!r}."
                decisions.append(
                    HeuristicDecision(
                        kind="unresolved",
                        target=baseline_path,
                        status="unresolved",
                        reason=reason,
                    )
                )
                unresolved_reasons.append(reason)
                continue

            source_operations.append(
                AddSourceAliasOperation(
                    path=baseline_path,
                    alias=candidate_path,
                    reason="Compatible rename drift can be absorbed as an extra alias.",
                )
            )
            audit_trail.append(
                PatchAuditEntry(
                    scope="source_schema",
                    action="add_source_alias",
                    target=f"{baseline_path}->{candidate_path}",
                    reason="Keep the canonical baseline field while recording the new incoming alias.",
                )
            )

            existing_ref = source_refs_by_path.get(baseline_path)
            if existing_ref is not None:
                mapping_operations.append(
                    RetargetSourceRefOperation(
                        source_ref_id=existing_ref.id,
                        new_path=candidate_path,
                        new_dtype=drift.candidate_signature.dominant_type if drift.candidate_signature else None,
                        new_cardinality=drift.candidate_signature.cardinality if drift.candidate_signature else None,
                        reason="Compiled converter should read from the renamed source path.",
                    )
                )
                audit_trail.append(
                    PatchAuditEntry(
                        scope="mapping_ir",
                        action="retarget_source_ref",
                        target=existing_ref.id,
                        reason="Preserve the existing MappingIR program while redirecting it to the new source path.",
                    )
                )
            else:
                new_source_ref = AddSourceReferenceOperation(
                    source_ref=_source_ref_from_field(field, candidate_path),
                    reason="Expose the renamed source path to MappingIR without regenerating the whole program.",
                )
                mapping_operations.append(new_source_ref)
                audit_trail.append(
                    PatchAuditEntry(
                        scope="mapping_ir",
                        action="add_source_ref",
                        target=new_source_ref.source_ref.id,
                        reason="The rename affects a schema field that was not exposed as a source ref yet.",
                    )
                )

            decisions.append(
                HeuristicDecision(
                    kind="rename_alignment",
                    target=f"{baseline_path}->{candidate_path}",
                    status="proposed",
                    reason="Safe rename alignment updates the schema alias list and retargets the MappingIR source reference.",
                )
            )
            continue

        if drift.kind == "added" and candidate_path and drift.candidate_signature is not None:
            source_operations.append(
                AddSourceFieldOperation(
                    field=_field_from_signature(candidate_path, drift.candidate_signature),
                    reason="Compatible additive drift can be recorded as a new optional source field.",
                )
            )
            audit_trail.append(
                PatchAuditEntry(
                    scope="source_schema",
                    action="add_source_field",
                    target=candidate_path,
                    reason="Record the new candidate field without regenerating unaffected source contracts.",
                )
            )
            decisions.append(
                HeuristicDecision(
                    kind="optional_field_addition",
                    target=candidate_path,
                    status="proposed",
                    reason="Additive compatible drift can be captured as a new optional source field.",
                )
            )
            continue

        if drift.kind == "changed" and baseline_path and drift.baseline_signature and drift.candidate_signature:
            if _is_safe_cast_candidate(drift.baseline_signature.dominant_type, drift.candidate_signature.dominant_type):
                matching_refs = [
                    source_ref
                    for source_ref in mapping_ir.source_refs
                    if source_ref.path == baseline_path
                ]
                if not matching_refs:
                    reason = f"No MappingIR source ref consumes the changed path {baseline_path!r}."
                    decisions.append(
                        HeuristicDecision(
                            kind="unresolved",
                            target=baseline_path,
                            status="unresolved",
                            reason=reason,
                        )
                    )
                    unresolved_reasons.append(reason)
                    continue

                for source_ref in matching_refs:
                    mapping_operations.append(
                        RetargetSourceRefOperation(
                            source_ref_id=source_ref.id,
                            new_path=baseline_path,
                            new_dtype=drift.candidate_signature.dominant_type,
                            new_cardinality=drift.candidate_signature.cardinality,
                            reason="Record the new observed source type before inserting a cast step.",
                        )
                    )
                    audit_trail.append(
                        PatchAuditEntry(
                            scope="mapping_ir",
                            action="retarget_source_ref",
                            target=source_ref.id,
                            reason="Update MappingIR source metadata to match the new input representation.",
                        )
                    )

                    for step in mapping_ir.steps:
                        if step.operation.source_ref != source_ref.id:
                            continue
                        if step.operation.kind not in {"copy", "rename", "cast"}:
                            continue
                        mapping_operations.append(
                            PromoteStepToCastOperation(
                                step_id=step.id,
                                to_type=source_ref.dtype,
                                reason="Safe cast insertion can preserve the baseline target semantics.",
                            )
                        )
                        audit_trail.append(
                            PatchAuditEntry(
                                scope="mapping_ir",
                                action="promote_step_to_cast",
                                target=step.id,
                                reason="Convert the changed source representation back into the expected baseline type.",
                            )
                        )

                decisions.append(
                    HeuristicDecision(
                        kind="safe_cast_insertion",
                        target=baseline_path,
                        status="proposed",
                        reason="The shared path stayed structurally compatible and can be normalized with a deterministic cast.",
                    )
                )
                continue

            if _can_extend_enum_mapping(drift.baseline_signature, drift.candidate_signature):
                baseline_values = set(drift.baseline_signature.enum_values)
                new_values = [
                    value
                    for value in drift.candidate_signature.enum_values
                    if value not in baseline_values
                ]
                enum_steps = [
                    step
                    for step in mapping_ir.steps
                    if step.operation.kind == "map_enum"
                    and any(
                        source_ref.id == step.operation.source_ref and source_ref.path == baseline_path
                        for source_ref in mapping_ir.source_refs
                    )
                ]
                if not enum_steps:
                    reason = f"No enum-mapping step can be extended for {baseline_path!r}."
                    decisions.append(
                        HeuristicDecision(
                            kind="unresolved",
                            target=baseline_path,
                            status="unresolved",
                            reason=reason,
                        )
                    )
                    unresolved_reasons.append(reason)
                    continue

                mapping_updates = {value: value.strip().lower() for value in new_values}
                for step in enum_steps:
                    mapping_operations.append(
                        ExtendEnumMappingOperation(
                            step_id=step.id,
                            mapping_updates=mapping_updates,
                            reason="Simple enum extensions can be handled locally without regenerating MappingIR.",
                        )
                    )
                    audit_trail.append(
                        PatchAuditEntry(
                            scope="mapping_ir",
                            action="extend_enum_mapping",
                            target=step.id,
                            reason="The new raw enum values fit the existing normalization pattern.",
                        )
                    )

                decisions.append(
                    HeuristicDecision(
                        kind="enum_extension",
                        target=baseline_path,
                        status="proposed",
                        reason="New enum-like values extend the baseline set without changing structure.",
                    )
                )
                continue

        reason = "Deterministic heuristics could not prove this drift is safe to patch locally."
        decisions.append(
            HeuristicDecision(
                kind="unresolved",
                target=baseline_path or candidate_path or "unknown",
                status="unresolved",
                reason=reason,
            )
        )
        unresolved_reasons.append(reason)

    patch = None
    if source_operations or mapping_operations:
        patch = ConverterPatch(
            classification=drift_report.classification,
            source_schema_operations=source_operations,
            mapping_ir_operations=mapping_operations,
            audit_trail=audit_trail,
        )

    return HeuristicResolution(
        compatible=not unresolved_reasons,
        classification=drift_report.classification,
        decisions=decisions,
        patch=patch,
        unresolved_reasons=unresolved_reasons,
    )


def _source_ref_from_field(field: SourceFieldSpec, path: str) -> SourceReference:
    """Build a MappingIR source reference from one source schema field.

    Args:
        field: Source schema field to expose.
        path: Candidate source path to assign to the source reference.

    Returns:
        A new source reference with a deterministic identifier.
    """

    return SourceReference(
        id=f"src_{_safe_identifier(path)}",
        path=path,
        dtype=field.dtype,
        cardinality=field.cardinality,
        description=field.description,
    )


def _field_from_signature(path: str, signature: FieldSignature) -> SourceFieldSpec:
    """Build a synthetic source field from one candidate signature.

    Args:
        path: Candidate path to record.
        signature: Candidate field signature.

    Returns:
        A source field specification suitable for source-schema patches.
    """

    return SourceFieldSpec(
        path=path,
        semantic_name=_safe_identifier(path),
        description="Field added by deterministic compatible-drift heuristics.",
        dtype=signature.dominant_type or "str",
        cardinality=signature.cardinality,
        nullable=signature.null_ratio > 0.0 or signature.present_ratio < 1.0,
        aliases=[],
        unit=signature.unit,
        examples=signature.enum_values[:3],
        confidence=0.8,
    )


def _safe_identifier(path: str) -> str:
    """Convert one path into a stable identifier fragment.

    Args:
        path: Canonical source path.

    Returns:
        A lower-case identifier fragment.
    """

    return (
        path.replace("[]", "")
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
        .lower()
    )


def _is_safe_cast_candidate(
    baseline_type: str | None,
    candidate_type: str | None,
) -> bool:
    """Return whether a changed shared path can be normalized with a cast.

    Args:
        baseline_type: Dominant baseline type.
        candidate_type: Dominant candidate type.

    Returns:
        ``True`` when the type change is a safe string/numeric normalization.
    """

    safe_pairs = {
        ("int", "str"),
        ("float", "str"),
        ("str", "int"),
        ("str", "float"),
        ("int", "float"),
        ("float", "int"),
    }
    return (baseline_type, candidate_type) in safe_pairs


def _can_extend_enum_mapping(
    baseline_signature: FieldSignature,
    candidate_signature: FieldSignature,
) -> bool:
    """Return whether a changed field looks like a simple enum extension.

    Args:
        baseline_signature: Baseline field signature.
        candidate_signature: Candidate field signature.

    Returns:
        ``True`` when the candidate enum set extends the baseline enum set.
    """

    baseline_values = set(baseline_signature.enum_values)
    candidate_values = set(candidate_signature.enum_values)
    if not baseline_values or not candidate_values:
        return False
    if baseline_signature.dominant_type != "str":
        return False
    return baseline_values < candidate_values
