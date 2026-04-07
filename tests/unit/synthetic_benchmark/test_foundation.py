"""Focused unit tests for the synthetic benchmark foundation package."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ai_converter.synthetic_benchmark import (
    BundleStore,
    L0TemplateSpec,
    ScenarioSamplerConfig,
    render_l0_payload,
    render_l1_payload,
    sample_canonical_scenario,
)
from ai_converter.validation import validate_structural_output

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "bundles"


class SyntheticTaskModel(BaseModel):
    """Target-side task model used for focused structural validation tests."""

    id: str
    name: str
    status: Literal["ready", "in_progress", "done"]
    duration_days: int
    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)


class SyntheticTargetModel(BaseModel):
    """Target-side root model used for the deterministic `L1` renderer tests."""

    tasks: list[SyntheticTaskModel]


def test_same_seed_produces_same_canonical_scenario() -> None:
    """Verify that the deterministic sampler is reproducible."""

    config = ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True)

    first = sample_canonical_scenario(11, config)
    second = sample_canonical_scenario(11, config)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_different_seeds_produce_different_scenarios() -> None:
    """Verify that different seeds produce materially different scenarios."""

    first = sample_canonical_scenario(11, ScenarioSamplerConfig(task_count=2))
    second = sample_canonical_scenario(12, ScenarioSamplerConfig(task_count=2))

    assert first.scenario.model_dump(mode="json") != second.scenario.model_dump(mode="json")


def test_l1_renderer_output_passes_target_validation() -> None:
    """Verify that deterministic `L1` rendering produces a valid target payload."""

    sampled = sample_canonical_scenario(7, ScenarioSamplerConfig(task_count=2))

    payload = render_l1_payload(sampled.scenario)
    result = validate_structural_output(payload, SyntheticTargetModel)

    assert result.valid is True
    assert result.validated_output is not None


def test_l0_renderer_preserves_core_semantics() -> None:
    """Verify that deterministic `L0` rendering preserves key task semantics."""

    sampled = sample_canonical_scenario(7, ScenarioSamplerConfig(task_count=2))
    template = L0TemplateSpec(
        wrap_task_object=True,
        extra_fields={"source": "synthetic"},
    )

    payload = render_l0_payload(sampled.scenario, template)
    assert isinstance(payload, dict)

    first_task = sampled.scenario.tasks[0]
    first_record = payload["records"][0]

    assert first_record["source"] == "synthetic"
    assert first_record["task"]["task_id"] == first_task.entity_id
    assert first_record["task"]["task_name"] == first_task.name
    assert first_record["task"]["status_text"] == first_task.status


def test_bundle_store_roundtrip_is_lossless() -> None:
    """Verify that bundle persistence round-trips without data loss."""

    sampled = sample_canonical_scenario(7, ScenarioSamplerConfig(task_count=2))
    template = L0TemplateSpec()
    store = BundleStore()
    bundle = store.build_bundle(
        sampled,
        template,
        dataset_id="synthetic-demo",
        bundle_id="bundle-1",
        created_at="2026-04-06T00:00:00+00:00",
    )

    output_dir = ROOT / ".pytest-local-tmp" / "synthetic-benchmark-roundtrip"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        export = store.save(bundle, output_dir / "bundle-1")
        loaded = store.load(export.root_dir)
        manifest_payload = json.loads(export.manifest_path.read_text(encoding="utf-8"))
        saved_files = _saved_file_names(export.root_dir)

        assert export.manifest_path.exists()
        assert saved_files == {
            "scenario.json",
            "template.json",
            "l0.json",
            "l1.json",
            "manifest.json",
            "metadata.json",
        }
        assert "source_oracle.json" not in saved_files
        assert manifest_payload == bundle.manifest.model_dump(mode="json")
        assert loaded.manifest.model_dump(mode="json") == bundle.manifest.model_dump(mode="json")
        assert loaded.model_dump(mode="json") == bundle.model_dump(mode="json")
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_metadata_contains_reproducibility_fields() -> None:
    """Verify that bundle metadata captures reproducibility fields."""

    sampled = sample_canonical_scenario(7, ScenarioSamplerConfig(task_count=2))
    store = BundleStore()
    bundle = store.build_bundle(
        sampled,
        L0TemplateSpec(),
        dataset_id="synthetic-demo",
        bundle_id="bundle-1",
        created_at="2026-04-06T00:00:00+00:00",
    )

    metadata = bundle.metadata.model_dump(mode="json")

    assert FIXTURE_ROOT.exists()
    assert metadata["bundle_id"] == "bundle-1"
    assert metadata["dataset_id"] == "synthetic-demo"
    assert metadata["seed"] == 7
    assert metadata["generator_version"] == "1.0"
    assert metadata["config_hash"]
    assert metadata["source_template_id"] == sampled.scenario.source_template_id


def _saved_file_names(root_dir: Path) -> set[str]:
    """Return the persisted bundle file names under one export directory."""

    return {path.name for path in root_dir.iterdir() if path.is_file()}
