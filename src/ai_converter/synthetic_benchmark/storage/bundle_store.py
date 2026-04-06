"""Filesystem persistence helpers for repo-local synthetic benchmark bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_converter.synthetic_benchmark.renderers import render_l0_payload, render_l1_payload
from ai_converter.synthetic_benchmark.scenario import CanonicalScenario, SampledScenario
from ai_converter.synthetic_benchmark.storage.models import DatasetBundle, DatasetBundleMetadata
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec


@dataclass(slots=True)
class BundleStoreExport:
    """Filesystem locations written by exporting one synthetic dataset bundle."""

    root_dir: Path
    scenario_path: Path
    template_path: Path
    l0_path: Path
    l1_path: Path
    metadata_path: Path


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
            metadata=DatasetBundleMetadata(
                bundle_id=resolved_bundle_id,
                dataset_id=dataset_id,
                seed=sampled.reproducibility.seed,
                generator_version=sampled.reproducibility.generator_version,
                config_hash=sampled.reproducibility.config_hash,
                created_at=resolved_created_at,
                source_template_id=sampled.scenario.source_template_id,
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
        metadata_path = root_dir / "metadata.json"

        _write_json(scenario_path, bundle.scenario.canonical_payload())
        _write_json(template_path, bundle.template.canonical_payload())
        _write_json(l0_path, bundle.l0_payload)
        _write_json(l1_path, bundle.l1_payload)
        _write_json(metadata_path, bundle.metadata.canonical_payload())

        return BundleStoreExport(
            root_dir=root_dir,
            scenario_path=scenario_path,
            template_path=template_path,
            l0_path=l0_path,
            l1_path=l1_path,
            metadata_path=metadata_path,
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
