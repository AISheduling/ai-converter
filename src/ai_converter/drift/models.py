"""Models for deterministic drift detection and local patch adaptation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.mapping_ir import SourceReference
from ai_converter.schema import SourceFieldSpec

DriftClassification = Literal[
    "no_change",
    "additive_compatible",
    "rename_compatible",
    "semantic_change",
    "breaking_change",
]


class FieldSignature(BaseModel):
    """Stable comparison signature derived from profile or schema facts."""

    model_config = ConfigDict(extra="forbid")

    path: str
    dominant_type: str | None = None
    present_ratio: float = Field(ge=0.0, le=1.0)
    null_ratio: float = Field(ge=0.0, le=1.0)
    cardinality: Literal["one", "many"] = "one"
    enum_values: list[str] = Field(default_factory=list)
    unit: str | None = None


class FieldDrift(BaseModel):
    """Comparison result for one source path or rename pair."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["added", "removed", "renamed", "changed"]
    baseline_path: str | None = None
    candidate_path: str | None = None
    classification: DriftClassification
    compatible: bool
    reasons: list[str] = Field(default_factory=list)
    score: float | None = None
    baseline_signature: FieldSignature | None = None
    candidate_signature: FieldSignature | None = None


class DriftReport(BaseModel):
    """Top-level deterministic drift classification output."""

    model_config = ConfigDict(extra="forbid")

    classification: DriftClassification
    compatible: bool
    baseline_fingerprint: str | None = None
    candidate_fingerprint: str | None = None
    field_drifts: list[FieldDrift] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PatchAuditEntry(BaseModel):
    """One audit-trail entry for a local source or mapping patch."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["source_schema", "mapping_ir"]
    action: str
    target: str
    reason: str


class AddSourceFieldOperation(BaseModel):
    """Append one new source field to the source schema contract."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_source_field"] = "add_source_field"
    field: SourceFieldSpec
    reason: str


class AddSourceAliasOperation(BaseModel):
    """Register one new alias for an existing source field."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_source_alias"] = "add_source_alias"
    path: str
    alias: str
    reason: str


class UpdateSourceFieldOperation(BaseModel):
    """Update selected attributes of an existing source field."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["update_source_field"] = "update_source_field"
    path: str
    dtype: str | None = None
    nullable: bool | None = None
    cardinality: Literal["one", "many"] | None = None
    unit: str | None = None
    append_examples: list[str] = Field(default_factory=list)
    reason: str


SourceSchemaPatchOperation = Annotated[
    AddSourceFieldOperation | AddSourceAliasOperation | UpdateSourceFieldOperation,
    Field(discriminator="kind"),
]


class RetargetSourceRefOperation(BaseModel):
    """Retarget one MappingIR source reference to a new source path."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["retarget_source_ref"] = "retarget_source_ref"
    source_ref_id: str
    new_path: str
    new_dtype: str | None = None
    new_cardinality: Literal["one", "many"] | None = None
    reason: str


class AddSourceReferenceOperation(BaseModel):
    """Append one new source reference to MappingIR."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_source_ref"] = "add_source_ref"
    source_ref: SourceReference
    reason: str


class PromoteStepToCastOperation(BaseModel):
    """Promote one copy-like step to a cast operation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["promote_step_to_cast"] = "promote_step_to_cast"
    step_id: str
    to_type: str
    reason: str


class ExtendEnumMappingOperation(BaseModel):
    """Extend one enum-mapping step with new raw-to-normalized values."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["extend_enum_mapping"] = "extend_enum_mapping"
    step_id: str
    mapping_updates: dict[str, str] = Field(default_factory=dict)
    reason: str


MappingIRPatchOperation = Annotated[
    RetargetSourceRefOperation
    | AddSourceReferenceOperation
    | PromoteStepToCastOperation
    | ExtendEnumMappingOperation,
    Field(discriminator="kind"),
]


class ConverterPatch(BaseModel):
    """Versioned local patch for source-schema and MappingIR updates."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    classification: DriftClassification
    source_schema_operations: list[SourceSchemaPatchOperation] = Field(default_factory=list)
    mapping_ir_operations: list[MappingIRPatchOperation] = Field(default_factory=list)
    audit_trail: list[PatchAuditEntry] = Field(default_factory=list)


class HeuristicDecision(BaseModel):
    """Machine-readable deterministic decision taken by the heuristics layer."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "alias_addition",
        "rename_alignment",
        "optional_field_addition",
        "safe_cast_insertion",
        "enum_extension",
        "unresolved",
    ]
    target: str
    status: Literal["proposed", "skipped", "unresolved"]
    reason: str


class HeuristicResolution(BaseModel):
    """Deterministic patch proposal built from a drift report."""

    model_config = ConfigDict(extra="forbid")

    compatible: bool
    classification: DriftClassification
    decisions: list[HeuristicDecision] = Field(default_factory=list)
    patch: ConverterPatch | None = None
    unresolved_reasons: list[str] = Field(default_factory=list)
