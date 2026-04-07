"""Filesystem persistence helpers for repo-local synthetic benchmark bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ai_converter.synthetic_benchmark.drift_generation import DriftSpec, apply_drift_to_payload
from ai_converter.synthetic_benchmark.drift_generation.models import AppliedDriftManifest
from ai_converter.synthetic_benchmark.renderers import render_l0_payload, render_l1_payload
from ai_converter.synthetic_benchmark.scenario import CanonicalScenario, SampledScenario
from ai_converter.synthetic_benchmark.storage.lineage import DriftLineage, build_drift_lineage
from ai_converter.synthetic_benchmark.storage.models import (
    DatasetBundle,
    DatasetBundleManifest,
    DatasetBundleMetadata,
)
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec


@dataclass(slots=True)
class BundleStoreExport:
    """Filesystem locations written by exporting one synthetic dataset bundle."""

    root_dir: Path
    scenario_path: Path
    template_path: Path
    l0_path: Path
    l1_path: Path
    manifest_path: Path
    metadata_path: Path
    drift_manifest_path: Path | None = None
    lineage_path: Path | None = None


class BundleStore:
    """Read and write deterministic synthetic bundle directories."""

    def build_bundle(
        self,
        sampled: SampledScenario,
        template: L0TemplateSpec,
        *,
        dataset_id: str,
        bundle_id: str | None = None,
        created_at: str | None = None,
    ) -> DatasetBundle:
        """Build one in-memory bundle from a sampled scenario and template.

        Args:
            sampled: Sampled canonical scenario and reproducibility metadata.
            template: Template controlling deterministic `L0` rendering.
            dataset_id: Stable dataset identifier.
            bundle_id: Optional explicit bundle identifier.
            created_at: Optional explicit timestamp for deterministic tests.

        Returns:
            Complete in-memory synthetic dataset bundle.
        """

        resolved_bundle_id = bundle_id or sampled.scenario.scenario_id
        resolved_created_at = created_at or datetime.now(UTC).isoformat()
        return DatasetBundle(
            scenario=sampled.scenario,
            template=template,
            l0_payload=render_l0_payload(sampled.scenario, template),
            l1_payload=render_l1_payload(sampled.scenario),
            manifest=_build_bundle_manifest(bundle_kind="base"),
            metadata=DatasetBundleMetadata(
                bundle_id=resolved_bundle_id,
                dataset_id=dataset_id,
                seed=sampled.reproducibility.seed,
                generator_version=sampled.reproducibility.generator_version,
                config_hash=sampled.reproducibility.config_hash,
                created_at=resolved_created_at,
                source_template_id=sampled.scenario.source_template_id,
                bundle_kind="base",
            ),
        )

    def build_drift_bundle(
        self,
        base_bundle: DatasetBundle,
        drift_spec: DriftSpec,
        *,
        bundle_id: str | None = None,
        created_at: str | None = None,
    ) -> DatasetBundle:
        """Build one drift bundle from a previously constructed base bundle.

        Args:
            base_bundle: Base synthetic bundle to drift.
            drift_spec: Drift spec to apply to the base `L0` payload.
            bundle_id: Optional explicit drift bundle identifier.
            created_at: Optional explicit timestamp for deterministic tests.

        Returns:
            Derived drift bundle with lineage and drift-manifest metadata.
        """

        resolved_bundle_id = bundle_id or f"{base_bundle.metadata.bundle_id}-{drift_spec.drift_id}"
        resolved_created_at = created_at or datetime.now(UTC).isoformat()
        records_key = (
            base_bundle.template.records_key
            if base_bundle.template.root_mode == "object"
            else None
        )
        drifted_l0, drift_manifest = apply_drift_to_payload(
            base_bundle.l0_payload,
            drift_spec,
            records_key=records_key,
        )
        lineage = build_drift_lineage(
            parent_bundle_id=base_bundle.metadata.bundle_id,
            drift_spec=drift_spec,
        )
        return DatasetBundle(
            scenario=base_bundle.scenario,
            template=base_bundle.template,
            l0_payload=drifted_l0,
            l1_payload=base_bundle.l1_payload,
            manifest=_build_bundle_manifest(
                bundle_kind="drift",
                has_drift_manifest=True,
                has_lineage=True,
            ),
            drift_manifest=drift_manifest,
            lineage=lineage,
            metadata=DatasetBundleMetadata(
                bundle_id=resolved_bundle_id,
                dataset_id=base_bundle.metadata.dataset_id,
                seed=base_bundle.metadata.seed,
                generator_version=base_bundle.metadata.generator_version,
                config_hash=base_bundle.metadata.config_hash,
                created_at=resolved_created_at,
                source_template_id=base_bundle.metadata.source_template_id,
                bundle_kind="drift",
            ),
        )

    def save(self, bundle: DatasetBundle, destination: str | Path) -> BundleStoreExport:
        """Persist one synthetic dataset bundle into a directory.

        Args:
            bundle: In-memory bundle to persist.
            destination: Bundle directory to populate.

        Returns:
            Concrete filesystem paths written during export.
        """

        root_dir = Path(destination)
        root_dir.mkdir(parents=True, exist_ok=True)
        scenario_path = root_dir / "scenario.json"
        template_path = root_dir / "template.json"
        l0_path = root_dir / "l0.json"
        l1_path = root_dir / "l1.json"
        manifest_path = root_dir / "manifest.json"
        metadata_path = root_dir / "metadata.json"
        drift_manifest_path = root_dir / "drift_manifest.json"
        lineage_path = root_dir / "lineage.json"
        manifest = _build_bundle_manifest(
            bundle_kind=bundle.metadata.bundle_kind,
            has_drift_manifest=bundle.drift_manifest is not None,
            has_lineage=bundle.lineage is not None,
        )

        _write_json(scenario_path, bundle.scenario.canonical_payload())
        _write_json(template_path, bundle.template.canonical_payload())
        _write_json(l0_path, bundle.l0_payload)
        _write_json(l1_path, bundle.l1_payload)
        _write_json(manifest_path, manifest.canonical_payload())
        _write_json(metadata_path, bundle.metadata.canonical_payload())
        if bundle.drift_manifest is not None:
            _write_json(drift_manifest_path, bundle.drift_manifest.canonical_payload())
        if bundle.lineage is not None:
            _write_json(lineage_path, bundle.lineage.canonical_payload())

        return BundleStoreExport(
            root_dir=root_dir,
            scenario_path=scenario_path,
            template_path=template_path,
            l0_path=l0_path,
            l1_path=l1_path,
            manifest_path=manifest_path,
            metadata_path=metadata_path,
            drift_manifest_path=drift_manifest_path if bundle.drift_manifest is not None else None,
            lineage_path=lineage_path if bundle.lineage is not None else None,
        )

    def load(self, root_dir: str | Path) -> DatasetBundle:
        """Load one synthetic dataset bundle from a directory.

        Args:
            root_dir: Directory containing bundle JSON files.

        Returns:
            Loaded in-memory bundle.
        """

        directory = Path(root_dir)
        return DatasetBundle(
            scenario=CanonicalScenario.model_validate(_read_json(directory / "scenario.json")),
            template=L0TemplateSpec.model_validate(_read_json(directory / "template.json")),
            l0_payload=_read_json(directory / "l0.json"),
            l1_payload=_read_json(directory / "l1.json"),
            manifest=DatasetBundleManifest.model_validate(_read_json(directory / "manifest.json")),
            drift_manifest=_load_optional_manifest(directory / "drift_manifest.json"),
            lineage=_load_optional_lineage(directory / "lineage.json"),
            metadata=DatasetBundleMetadata.model_validate(_read_json(directory / "metadata.json")),
        )


def _write_json(path: Path, payload: Any) -> None:
    """Write one JSON payload with deterministic formatting.

    Args:
        path: Destination path for the JSON file.
        payload: JSON-compatible payload to serialize.
    """

    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    """Read one JSON payload from disk.

    Args:
        path: Source JSON file.

    Returns:
        Parsed JSON payload.
    """

    return json.loads(path.read_text(encoding="utf-8"))


def _build_bundle_manifest(
    *,
    bundle_kind: Literal["base", "drift"],
    has_drift_manifest: bool = False,
    has_lineage: bool = False,
) -> DatasetBundleManifest:
    """Build the deterministic artifact manifest for one persisted bundle."""

    return DatasetBundleManifest(
        bundle_kind=bundle_kind,
        drift_manifest_path="drift_manifest.json" if has_drift_manifest else None,
        lineage_path="lineage.json" if has_lineage else None,
    )


def _load_optional_manifest(path: Path) -> AppliedDriftManifest | None:
    """Load an optional applied-drift manifest from disk.

    Args:
        path: Candidate drift-manifest file path.

    Returns:
        Parsed drift manifest or `None` when the file is absent.
    """

    if not path.exists():
        return None

    return AppliedDriftManifest.model_validate(_read_json(path))


def _load_optional_lineage(path: Path) -> DriftLineage | None:
    """Load optional drift lineage metadata from disk.

    Args:
        path: Candidate lineage file path.

    Returns:
        Parsed drift lineage or `None` when the file is absent.
    """

    if not path.exists():
        return None
    return DriftLineage.model_validate(_read_json(path))
