"""Versioned storage models for persisted synthetic benchmark bundles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ai_converter.synthetic_benchmark.drift_generation.models import AppliedDriftManifest
from ai_converter.synthetic_benchmark.scenario import CanonicalScenario
from ai_converter.synthetic_benchmark.storage.lineage import DriftLineage
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec

DATASET_BUNDLE_VERSION = "1.0"


class DatasetBundleMetadata(BaseModel):
    """Repo-local metadata persisted alongside one synthetic dataset bundle."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    dataset_id: str
    seed: int
    generator_version: str
    config_hash: str
    created_at: str
    source_template_id: str
    bundle_kind: Literal["base", "drift"] = "base"

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible metadata payload.

        Returns:
            JSON-compatible metadata payload.
        """

        return self.model_dump(mode="json")


class DatasetBundle(BaseModel):
    """Complete in-memory synthetic dataset bundle for one scenario sample."""

    model_config = ConfigDict(extra="forbid")

    version: str = DATASET_BUNDLE_VERSION
    scenario: CanonicalScenario
    template: L0TemplateSpec
    l0_payload: dict[str, Any] | list[dict[str, Any]]
    l1_payload: dict[str, Any]
    drift_manifest: AppliedDriftManifest | None = None
    lineage: DriftLineage | None = None
    metadata: DatasetBundleMetadata
