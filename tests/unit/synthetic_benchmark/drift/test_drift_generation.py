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
REQUIRED_FR4_DRIFT_CLASSES = {
    "additive",
    "rename",
    "nesting",
    "sparsity",
    "enum/value format",
    "split/merge field",
    "heterogeneous-object",
}
FIXTURE_PROOF_MATRIX = {
    "add_priority_spec.json": {
        "drift_classes": {"additive"},
        "operator_kinds": ["add_field"],
    },
    "rename_status_spec.json": {
        "drift_classes": {"rename"},
        "operator_kinds": ["rename_field"],
    },
    "high_nesting_spec.json": {
        "drift_classes": {"nesting"},
        "operator_kinds": ["nest_field"],
    },
    "enum_value_format_spec.json": {
        "drift_classes": {"enum/value format"},
        "operator_kinds": ["change_enum_surface", "change_value_format"],
    },
    "split_merge_spec.json": {
        "drift_classes": {"split/merge field"},
        "operator_kinds": ["split_field", "merge_fields"],
    },
    "sparse_heterogeneous_spec.json": {
        "drift_classes": {"sparsity", "heterogeneous-object"},
        "operator_kinds": ["inject_sparse_objects"],
    },
}


def test_fixture_matrix_covers_required_epic_drift_classes() -> None:
    """Verify that the focused fixture matrix covers every required `FR-4` class."""

    fixture_names = {path.name for path in FIXTURE_ROOT.glob("*_spec.json")}
    assert fixture_names == set(FIXTURE_PROOF_MATRIX)

    proved_classes = set().union(
        *(entry["drift_classes"] for entry in FIXTURE_PROOF_MATRIX.values())
    )
    assert proved_classes == REQUIRED_FR4_DRIFT_CLASSES

    for filename, entry in FIXTURE_PROOF_MATRIX.items():
        drift_spec = _load_drift_spec(filename)
        assert [operator.kind for operator in drift_spec.operators] == entry["operator_kinds"]


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


def test_enum_and_value_format_drift_is_proven_locally() -> None:
    """Verify that enum-surface and value-format drift are covered deterministically."""

    base_bundle = _build_base_bundle()
    drift_spec = _load_drift_spec("enum_value_format_spec.json")

    drifted_payload, manifest = apply_drift_to_payload(
        base_bundle.l0_payload,
        drift_spec,
        records_key=base_bundle.template.records_key,
    )

    records = drifted_payload["records"]

    assert records[0]["status_text"] == "READY_NOW"
    assert records[2]["status_text"] == "WORKING"
    assert [record["duration_days"] for record in records] == ["7 days", "9 days", "2 days"]
    assert manifest.compatibility_class == "breaking_change"
    assert manifest.compatible is False
    assert manifest.operator_sequence == ["change_enum_surface", "change_value_format"]
    assert manifest.changed_paths == ["duration_days", "status_text"]
    assert manifest.changed_record_indexes == [0, 1, 2]


def test_split_and_merge_drift_is_proven_locally() -> None:
    """Verify that split/merge drift is covered deterministically."""

    base_bundle = _build_base_bundle()
    drift_spec = _load_drift_spec("split_merge_spec.json")

    drifted_payload, manifest = apply_drift_to_payload(
        base_bundle.l0_payload,
        drift_spec,
        records_key=base_bundle.template.records_key,
    )

    first_record = drifted_payload["records"][0]

    assert "task_name" not in first_record
    assert "task_id" not in first_record
    assert "status_text" not in first_record
    assert first_record["task_name_left"] == "Task"
    assert first_record["task_name_right"] == "1 Review"
    assert first_record["task_label"] == "T-07-01:ready"
    assert manifest.compatibility_class == "breaking_change"
    assert manifest.compatible is False
    assert manifest.operator_sequence == ["split_field", "merge_fields"]
    assert manifest.changed_paths == [
        "status_text",
        "task_id",
        "task_label",
        "task_name",
        "task_name_left",
        "task_name_right",
    ]
    assert manifest.changed_record_indexes == [0, 1, 2]


def test_sparse_drift_creates_heterogeneous_records() -> None:
    """Verify that sparse-object drift produces auditable heterogeneous records."""

    base_bundle = _build_base_bundle()
    drift_spec = _load_drift_spec("sparse_heterogeneous_spec.json")

    drifted_payload, manifest = apply_drift_to_payload(
        base_bundle.l0_payload,
        drift_spec,
        records_key=base_bundle.template.records_key,
    )

    records = drifted_payload["records"]
    field_sets = {frozenset(record) for record in records}

    assert records[0] == {"task_id": "T-07-01", "status_text": "ready"}
    assert records[1] == {
        "task_id": "T-07-02",
        "task_name": "Task 2 Deploy",
        "status_text": "ready",
        "duration_days": 9,
    }
    assert records[2] == {"task_id": "T-07-03", "status_text": "in_progress"}
    assert field_sets == {
        frozenset({"task_id", "status_text"}),
        frozenset({"task_id", "task_name", "status_text", "duration_days"}),
    }
    assert manifest.compatibility_class == "breaking_change"
    assert manifest.compatible is False
    assert manifest.operator_sequence == ["inject_sparse_objects"]
    assert manifest.changed_paths == ["status_text", "task_id"]
    assert manifest.changed_record_indexes == [0, 2]


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
