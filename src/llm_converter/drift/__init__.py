"""Public exports for deterministic drift detection and patch adaptation."""

from __future__ import annotations

from .classifier import classify_drift
from .heuristics import propose_compatible_patch
from .models import (
    AddSourceAliasOperation,
    AddSourceFieldOperation,
    AddSourceReferenceOperation,
    ConverterPatch,
    DriftReport,
    ExtendEnumMappingOperation,
    FieldDrift,
    FieldSignature,
    HeuristicDecision,
    HeuristicResolution,
    PatchAuditEntry,
    PromoteStepToCastOperation,
    RetargetSourceRefOperation,
    UpdateSourceFieldOperation,
)
from .patch_apply import PatchApplyError, apply_converter_patch, apply_mapping_ir_patch, apply_source_schema_patch

__all__ = [
    "AddSourceAliasOperation",
    "AddSourceFieldOperation",
    "AddSourceReferenceOperation",
    "ConverterPatch",
    "DriftReport",
    "ExtendEnumMappingOperation",
    "FieldDrift",
    "FieldSignature",
    "HeuristicDecision",
    "HeuristicResolution",
    "PatchApplyError",
    "PatchAuditEntry",
    "PromoteStepToCastOperation",
    "RetargetSourceRefOperation",
    "UpdateSourceFieldOperation",
    "apply_converter_patch",
    "apply_mapping_ir_patch",
    "apply_source_schema_patch",
    "classify_drift",
    "propose_compatible_patch",
]
