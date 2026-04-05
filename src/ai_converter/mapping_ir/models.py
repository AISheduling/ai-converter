"""Formal MappingIR models used by the offline synthesis pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_OPERATION_KINDS = (
    "copy",
    "rename",
    "cast",
    "map_enum",
    "unit_convert",
    "split",
    "merge",
    "nest",
    "unnest",
    "derive",
    "default",
    "drop",
    "validate",
)

OperationKind = Literal[
    "copy",
    "rename",
    "cast",
    "map_enum",
    "unit_convert",
    "split",
    "merge",
    "nest",
    "unnest",
    "derive",
    "default",
    "drop",
    "validate",
]


class SourceReference(BaseModel):
    """Canonical source reference available to a mapping program.

    Attributes:
        id: Stable source identifier used by mapping steps.
        path: Canonical source path from the source schema contract.
        dtype: Canonical source-side type label.
        cardinality: Whether the source ref resolves to one or many values.
        description: Optional human-readable note for prompt context.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    dtype: str = Field(min_length=1)
    cardinality: Literal["one", "many"] = "one"
    description: str | None = None

    @field_validator("id", "path", "dtype")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        """Normalize required string fields.

        Args:
            value: Raw string value from the model input.

        Returns:
            The stripped string value.

        Raises:
            ValueError: If the normalized value is empty.
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class StepOperation(BaseModel):
    """Typed operation payload for one mapping step.

    Attributes:
        kind: Supported operation kind for the current step.
        source_ref: Optional single source reference consumed by the step.
        source_refs: Optional collection of source references for multi-input steps.
        step_refs: Optional collection of upstream step references.
        child_keys: Explicit semantic child keys for ``nest`` keyed by upstream step ref.
        to_type: Target scalar type used by ``cast``.
        mapping: Enum remapping table used by ``map_enum``.
        from_unit: Source unit for ``unit_convert``.
        to_unit: Target unit for ``unit_convert``.
        factor: Numeric scale factor for ``unit_convert``.
        delimiter: Delimiter used by ``split`` or ``merge``.
        child_path: Nested child path used by ``unnest``.
        expression: Deterministic expression used by ``derive``.
        value: Literal default value used by ``default``.
        predicate: Validation predicate used by ``validate``.
        message: Human-readable validation message.
    """

    model_config = ConfigDict(extra="forbid")

    kind: OperationKind
    source_ref: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    step_refs: list[str] = Field(default_factory=list)
    child_keys: dict[str, str] = Field(default_factory=dict)
    to_type: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict)
    from_unit: str | None = None
    to_unit: str | None = None
    factor: float | None = None
    delimiter: str | None = None
    child_path: str | None = None
    expression: str | None = None
    value: Any = None
    predicate: str | None = None
    message: str | None = None

    @field_validator("source_ref", "to_type", "from_unit", "to_unit", "delimiter", "child_path", "expression", "predicate", "message")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        """Normalize optional text fields.

        Args:
            value: Raw optional text value.

        Returns:
            The stripped value when present, otherwise ``None``.
        """

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("source_refs", "step_refs")
    @classmethod
    def _strip_reference_lists(cls, values: list[str]) -> list[str]:
        """Normalize reference lists while preserving order.

        Args:
            values: Raw reference list from the model input.

        Returns:
            A list with stripped, non-empty references.
        """

        return [value.strip() for value in values if value.strip()]

    @field_validator("child_keys")
    @classmethod
    def _strip_child_keys(cls, values: dict[str, str]) -> dict[str, str]:
        """Normalize the explicit child-key contract for ``nest`` operations.

        Args:
            values: Raw mapping from upstream step refs to semantic child keys.

        Returns:
            A mapping with stripped, non-empty step refs and child keys.

        Raises:
            ValueError: If any normalized step ref or child key is blank.
        """

        normalized: dict[str, str] = {}
        for step_ref, child_key in values.items():
            normalized_step_ref = step_ref.strip()
            normalized_child_key = child_key.strip()
            if not normalized_step_ref or not normalized_child_key:
                raise ValueError("child_keys must not contain blank step refs or child keys")
            normalized[normalized_step_ref] = normalized_child_key
        return normalized


class MappingStep(BaseModel):
    """Deterministic transformation step inside ``MappingIR``.

    Attributes:
        id: Stable identifier used by assignments and downstream steps.
        operation: Typed operation payload describing the transformation.
        depends_on: Extra upstream step ids used to build dependency edges.
        description: Optional human-readable step summary.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    operation: StepOperation
    depends_on: list[str] = Field(default_factory=list)
    description: str | None = None

    @field_validator("id")
    @classmethod
    def _strip_id(cls, value: str) -> str:
        """Normalize one step identifier.

        Args:
            value: Raw step identifier.

        Returns:
            The stripped step identifier.

        Raises:
            ValueError: If the identifier is blank.
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("step id must not be blank")
        return normalized

    @field_validator("depends_on")
    @classmethod
    def _strip_dependencies(cls, values: list[str]) -> list[str]:
        """Normalize dependency identifiers.

        Args:
            values: Raw dependency list.

        Returns:
            A list with stripped, non-empty dependency ids.
        """

        return [value.strip() for value in values if value.strip()]


class TargetAssignment(BaseModel):
    """Assignment from one mapping step output into a target path.

    Attributes:
        step_id: Upstream step whose output should be written to the target.
        target_path: Canonical target path in the target schema card.
        allow_overwrite: Whether a conflicting write to the same path is allowed.
        required: Whether this assignment is expected to be produced.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    target_path: str = Field(min_length=1)
    allow_overwrite: bool = False
    required: bool = True

    @field_validator("step_id", "target_path")
    @classmethod
    def _strip_assignment_text(cls, value: str) -> str:
        """Normalize assignment identifiers and paths.

        Args:
            value: Raw assignment text value.

        Returns:
            The stripped text value.

        Raises:
            ValueError: If the normalized value is empty.
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("assignment values must not be blank")
        return normalized


class ConditionClause(BaseModel):
    """Optional precondition or postcondition attached to ``MappingIR``.

    Attributes:
        kind: Condition kind such as ``exists`` or ``non_null``.
        ref: Referenced source ref or step id.
        value: Optional comparison value.
        description: Optional human-readable explanation.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exists", "non_null", "equals"] = "exists"
    ref: str = Field(min_length=1)
    value: Any = None
    description: str | None = None

    @field_validator("ref")
    @classmethod
    def _strip_ref(cls, value: str) -> str:
        """Normalize the referenced identifier.

        Args:
            value: Raw condition reference.

        Returns:
            The stripped condition reference.

        Raises:
            ValueError: If the normalized value is empty.
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("condition refs must not be blank")
        return normalized


class MappingIR(BaseModel):
    """Formal deterministic mapping program synthesized between L0 and L1.

    Attributes:
        version: Stable IR version string.
        source_refs: Canonical source references available to the program.
        steps: Ordered transformation steps.
        assignments: Target assignments emitted by the program.
        preconditions: Optional source-side guard conditions.
        postconditions: Optional target-side validation conditions.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    source_refs: list[SourceReference] = Field(default_factory=list)
    steps: list[MappingStep] = Field(default_factory=list)
    assignments: list[TargetAssignment] = Field(default_factory=list)
    preconditions: list[ConditionClause] = Field(default_factory=list)
    postconditions: list[ConditionClause] = Field(default_factory=list)

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation of the IR.

        Returns:
            A JSON-compatible payload with sorted keys suitable for hashing.
        """

        return self.model_dump(mode="json")
