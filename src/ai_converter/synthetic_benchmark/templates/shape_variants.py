"""Shape-variant contracts for deterministic heterogeneous `L0` task records."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import OptionalTaskField, TaskFieldAliases

SHAPE_VARIANT_POLICY_VERSION = "1.0"
ShapeVariantAssignmentMode = Literal["round_robin", "hash"]


class ShapeVariantSpec(BaseModel):
    """One deterministic task-record shape used during `L0` rendering."""

    model_config = ConfigDict(extra="forbid")

    variant_id: str
    weight: int = Field(default=1, ge=1)
    wrap_task_object: bool | None = None
    task_object_key: str | None = None
    record_envelope_key: str | None = None
    field_aliases: TaskFieldAliases | None = None
    optional_fields: list[OptionalTaskField] | None = None
    rare_extra_fields: dict[str, Any] = Field(default_factory=dict)
    vendor_extra_fields: dict[str, Any] = Field(default_factory=dict)


class ShapeVariantPolicy(BaseModel):
    """Deterministic policy for assigning task-record shape variants."""

    model_config = ConfigDict(extra="forbid")

    version: str = SHAPE_VARIANT_POLICY_VERSION
    assignment_mode: ShapeVariantAssignmentMode = "round_robin"
    selection_salt: str = "shape-variant-policy"
    variants: list[ShapeVariantSpec] = Field(default_factory=list)

    @field_validator("variants")
    @classmethod
    def _validate_variants(cls, value: list[ShapeVariantSpec]) -> list[ShapeVariantSpec]:
        """Reject empty variant lists when a policy is configured.

        Args:
            value: Candidate shape variants.

        Returns:
            The validated non-empty variant list.

        Raises:
            ValueError: If the policy has no variants.
        """

        if not value:
            raise ValueError("shape_variant_policy must contain at least one variant")
        return value

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible shape policy payload.

        Returns:
            JSON-compatible policy payload.
        """

        return self.model_dump(mode="json")


def select_shape_variant(
    policy: ShapeVariantPolicy | None,
    *,
    record_index: int,
    stable_key: str,
) -> ShapeVariantSpec | None:
    """Resolve the deterministic shape variant for one rendered record.

    Args:
        policy: Optional variant-selection policy attached to the template.
        record_index: Stable zero-based record index in the rendered payload.
        stable_key: Stable scenario/task-specific key used for hash-based selection.

    Returns:
        The selected shape variant, or `None` when the template has no policy.
    """

    if policy is None:
        return None
    weighted_variants = _expand_weighted_variants(policy.variants)
    if policy.assignment_mode == "round_robin":
        return weighted_variants[record_index % len(weighted_variants)]
    digest = hashlib.sha256(
        json.dumps(
            {
                "selection_salt": policy.selection_salt,
                "stable_key": stable_key,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return weighted_variants[int(digest[:8], 16) % len(weighted_variants)]


def _expand_weighted_variants(variants: list[ShapeVariantSpec]) -> list[ShapeVariantSpec]:
    """Expand weighted variants into a deterministic selection list.

    Args:
        variants: Configured shape variants.

    Returns:
        Weighted variant list ordered as configured.
    """

    expanded: list[ShapeVariantSpec] = []
    for variant in variants:
        expanded.extend([variant] * variant.weight)
    return expanded
