"""Versioned storage models for persisted synthetic benchmark bundles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.synthetic_benchmark.drift_generation.models import AppliedDriftManifest
from ai_converter.synthetic_benchmark.scenario import CanonicalScenario
from ai_converter.synthetic_benchmark.storage.lineage import DriftLineage
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec

DATASET_BUNDLE_VERSION = "1.0"
DATASET_BUNDLE_MANIFEST_VERSION = "1.0"


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


class DatasetBundleManifest(BaseModel):
    """Deterministic file manifest for one persisted synthetic dataset bundle."""

    model_config = ConfigDict(extra="forbid")

    version: str = DATASET_BUNDLE_MANIFEST_VERSION
    bundle_kind: Literal["base", "drift"] = "base"
    scenario_path: str = "scenario.json"
    template_path: str = "template.json"
    l0_path: str = "l0.json"
    l1_path: str = "l1.json"
    metadata_path: str = "metadata.json"
    drift_manifest_path: str | None = None
    lineage_path: str | None = None

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible manifest payload.

        Returns:
            JSON-compatible manifest payload.
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
    manifest: DatasetBundleManifest = Field(default_factory=DatasetBundleManifest)
    drift_manifest: AppliedDriftManifest | None = None
    lineage: DriftLineage | None = None
    metadata: DatasetBundleMetadata
