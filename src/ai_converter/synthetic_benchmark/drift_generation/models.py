"""Typed contracts for deterministic synthetic `L0` drift generation."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_converter.drift.models import DriftClassification, DriftReport

DRIFT_SPEC_VERSION = "1.0"
APPLIED_DRIFT_MANIFEST_VERSION = "1.0"
DriftSeverity = Literal["low", "medium", "high"]


class DriftOperatorBase(BaseModel):
    """Shared configuration for one deterministic drift operator."""

    model_config = ConfigDict(extra="forbid")

    record_indexes: list[int] = Field(default_factory=list)


class AddFieldOperator(DriftOperatorBase):
    """Add one deterministic field to selected records."""

    kind: Literal["add_field"] = "add_field"
    path: str
    value: Any


class DropOptionalFieldOperator(DriftOperatorBase):
    """Drop one optional field from selected records."""

    kind: Literal["drop_optional_field"] = "drop_optional_field"
    path: str


class RenameFieldOperator(DriftOperatorBase):
    """Rename one field within selected records."""

    kind: Literal["rename_field"] = "rename_field"
    path: str
    new_path: str


class NestFieldOperator(DriftOperatorBase):
    """Move one field into a nested path inside selected records."""

    kind: Literal["nest_field"] = "nest_field"
    path: str
    new_path: str


class FlattenFieldOperator(DriftOperatorBase):
    """Move one nested field to a shallower path inside selected records."""

    kind: Literal["flatten_field"] = "flatten_field"
    path: str
    new_path: str


class SplitFieldOperator(DriftOperatorBase):
    """Split one scalar field into two derived sibling fields."""

    kind: Literal["split_field"] = "split_field"
    path: str
    new_paths: list[str] = Field(min_length=2, max_length=2)
    separator: str = " "


class MergeFieldsOperator(DriftOperatorBase):
    """Merge multiple fields into one derived scalar field."""

    kind: Literal["merge_fields"] = "merge_fields"
    paths: list[str] = Field(min_length=2)
    new_path: str
    separator: str = " "


class ChangeValueFormatOperator(DriftOperatorBase):
    """Change the surface format of one field while keeping deterministic behavior."""

    kind: Literal["change_value_format"] = "change_value_format"
    path: str
    format_style: Literal["duration_text", "duration_iso", "stringify"] = "stringify"


class ChangeEnumSurfaceOperator(DriftOperatorBase):
    """Map enum-like source values onto a new source-side surface."""

    kind: Literal["change_enum_surface"] = "change_enum_surface"
    path: str
    mapping: dict[str, str] = Field(default_factory=dict)


class InjectSparseObjectsOperator(DriftOperatorBase):
    """Reduce selected records to sparse objects that keep only named fields."""

    kind: Literal["inject_sparse_objects"] = "inject_sparse_objects"
    keep_paths: list[str] = Field(default_factory=list)


SyntheticDriftOperator = Annotated[
    AddFieldOperator
    | DropOptionalFieldOperator
    | RenameFieldOperator
    | NestFieldOperator
    | FlattenFieldOperator
    | SplitFieldOperator
    | MergeFieldsOperator
    | ChangeValueFormatOperator
    | ChangeEnumSurfaceOperator
    | InjectSparseObjectsOperator,
    Field(discriminator="kind"),
]


class DriftSpec(BaseModel):
    """Versioned configuration for one deterministic synthetic drift run."""

    model_config = ConfigDict(extra="forbid")

    version: str = DRIFT_SPEC_VERSION
    drift_id: str
    drift_type: str
    severity: DriftSeverity
    compatibility_class: DriftClassification
    operators: list[SyntheticDriftOperator] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("operators")
    @classmethod
    def _validate_operators(
        cls,
        value: list[SyntheticDriftOperator],
    ) -> list[SyntheticDriftOperator]:
        """Reject empty drift specs.

        Args:
            value: Candidate drift operators.

        Returns:
            The validated non-empty operator list.

        Raises:
            ValueError: If the drift spec is empty.
        """

        if not value:
            raise ValueError("drift specs must include at least one operator")
        return value

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible drift-spec payload.

        Returns:
            JSON-compatible drift-spec payload.
        """

        return self.model_dump(mode="json")


class AppliedDriftManifest(BaseModel):
    """Machine-readable result of applying one drift spec."""

    model_config = ConfigDict(extra="forbid")

    version: str = APPLIED_DRIFT_MANIFEST_VERSION
    drift_id: str
    drift_type: str
    severity: DriftSeverity
    compatibility_class: DriftClassification
    compatible: bool
    operator_sequence: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    changed_record_indexes: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    drift_report: DriftReport | None = None

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible applied-manifest payload.

        Returns:
            JSON-compatible applied-manifest payload.
        """

        return self.model_dump(mode="json")
