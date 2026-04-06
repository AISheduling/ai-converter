"""Lineage models for linking drift bundles to their parent synthetic bundles."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.drift.models import DriftClassification
from ai_converter.synthetic_benchmark.drift_generation.models import DriftSeverity, DriftSpec

DRIFT_LINEAGE_VERSION = "1.0"


class DriftLineage(BaseModel):
    """Lineage metadata describing how one drift bundle derives from a parent."""

    model_config = ConfigDict(extra="forbid")

    version: str = DRIFT_LINEAGE_VERSION
    parent_bundle_id: str
    drift_id: str
    drift_type: str
    severity: DriftSeverity
    operator_sequence: list[str] = Field(default_factory=list)
    compatibility_class: DriftClassification

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible lineage payload.

        Returns:
            JSON-compatible lineage payload.
        """

        return self.model_dump(mode="json")


def build_drift_lineage(
    parent_bundle_id: str,
    drift_spec: DriftSpec,
) -> DriftLineage:
    """Build lineage metadata for one synthetic drift bundle.

    Args:
        parent_bundle_id: Identifier of the parent base bundle.
        drift_spec: Drift spec applied to create the child bundle.

    Returns:
        Drift lineage metadata for the derived bundle.
    """

    return DriftLineage(
        parent_bundle_id=parent_bundle_id,
        drift_id=drift_spec.drift_id,
        drift_type=drift_spec.drift_type,
        severity=drift_spec.severity,
        operator_sequence=[operator.kind for operator in drift_spec.operators],
        compatibility_class=drift_spec.compatibility_class,
    )
