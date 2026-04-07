"""Focused unit tests for deterministic synthetic drift generation."""

from __future__ import annotations

import shutil
from pathlib import Path

from ai_converter.synthetic_benchmark import (
    BundleStore,
    DriftSpec,
    L0TemplateSpec,
    ScenarioSamplerConfig,
    apply_drift_to_payload,
    sample_canonical_scenario,
)

ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "drift"


def test_drift_operator_adds_expected_manifest() -> None:
    """Verify that additive drift records a deterministic manifest."""

    base_bundle = _build_base_bundle()
    drift_spec = _load_drift_spec("add_priority_spec.json")

    drifted_payload, manifest = apply_drift_to_payload(
        base_bundle.l0_payload,
        drift_spec,
        records_key=base_bundle.template.records_key,
    )

    assert isinstance(drifted_payload, dict)
    assert drifted_payload["records"][0]["task_priority"] == "P1"
    assert manifest.compatibility_class == "additive_compatible"
    assert manifest.compatible is True
    assert manifest.changed_paths == ["task_priority"]
    assert manifest.changed_record_indexes == [0, 1]


def test_compatible_drift_preserves_gold_l1() -> None:
    """Verify that a compatible drift bundle keeps the base gold `L1` payload."""

    store = BundleStore()
    base_bundle = _build_base_bundle()
    drift_bundle = store.build_drift_bundle(
        base_bundle,
        _load_drift_spec("rename_status_spec.json"),
        bundle_id="bundle-1-rename",
        created_at="2026-04-06T00:00:00+00:00",
    )

    assert drift_bundle.l1_payload == base_bundle.l1_payload
    assert drift_bundle.metadata.bundle_kind == "drift"
    assert drift_bundle.lineage is not None
    assert drift_bundle.lineage.compatibility_class == "rename_compatible"
    assert drift_bundle.drift_manifest is not None
    assert drift_bundle.drift_manifest.compatible is True


def test_high_severity_drift_changes_l0_structure() -> None:
    """Verify that high-severity drift materially changes the `L0` structure."""

    base_bundle = _build_base_bundle()
    drift_spec = _load_drift_spec("high_nesting_spec.json")

    drifted_payload, manifest = apply_drift_to_payload(
        base_bundle.l0_payload,
        drift_spec,
        records_key=base_bundle.template.records_key,
    )

    assert drifted_payload != base_bundle.l0_payload
    assert isinstance(drifted_payload, dict)
    assert "status" in drifted_payload["records"][0]
    assert "details" in drifted_payload["records"][0]["status"]
    assert manifest.compatible is False
    assert manifest.compatibility_class in {"semantic_change", "breaking_change"}


def test_lineage_links_drift_bundle_to_parent() -> None:
    """Verify that saved drift bundles round-trip with lineage metadata intact."""

    store = BundleStore()
    base_bundle = _build_base_bundle()
    drift_bundle = store.build_drift_bundle(
        base_bundle,
        _load_drift_spec("add_priority_spec.json"),
        bundle_id="bundle-1-drift",
        created_at="2026-04-06T00:00:00+00:00",
    )

    output_dir = ROOT / ".pytest-local-tmp" / "synthetic-benchmark-drift-roundtrip"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        export = store.save(drift_bundle, output_dir / "bundle-1-drift")
        loaded = store.load(export.root_dir)
        saved_files = {path.name for path in export.root_dir.iterdir() if path.is_file()}

        assert export.manifest_path.exists()
        assert export.drift_manifest_path is not None
        assert export.lineage_path is not None
        assert saved_files == {
            "scenario.json",
            "template.json",
            "l0.json",
            "l1.json",
            "manifest.json",
            "metadata.json",
            "drift_manifest.json",
            "lineage.json",
        }
        assert "source_oracle.json" not in saved_files
        assert drift_bundle.lineage is not None
        assert drift_bundle.lineage.parent_bundle_id == base_bundle.metadata.bundle_id
        assert loaded.manifest.bundle_kind == "drift"
        assert loaded.manifest.drift_manifest_path == "drift_manifest.json"
        assert loaded.manifest.lineage_path == "lineage.json"
        assert loaded.model_dump(mode="json") == drift_bundle.model_dump(mode="json")
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _build_base_bundle():
    """Build the deterministic base bundle shared by drift tests."""

    sampled = sample_canonical_scenario(
        7,
        ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True),
    )
    return BundleStore().build_bundle(
        sampled,
        L0TemplateSpec(),
        dataset_id="synthetic-demo",
        bundle_id="bundle-1",
        created_at="2026-04-06T00:00:00+00:00",
    )


def _load_drift_spec(filename: str) -> DriftSpec:
    """Load one deterministic drift spec fixture.

    Args:
        filename: Fixture filename under the synthetic drift fixture root.

    Returns:
        Parsed deterministic drift spec.
    """

    return DriftSpec.model_validate_json((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
