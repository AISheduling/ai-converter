"""Focused unit tests for schema contracts and evidence packing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from ai_converter.profiling.report_builder import build_profile_report
from ai_converter.schema.evidence_packer import pack_profile_evidence
from ai_converter.schema.source_spec_aggregator import merge_source_schema_candidates
from ai_converter.schema.source_spec_models import (
    SOURCE_SCHEMA_SPEC_VERSION,
    SourceFieldSpec,
    SourceSchemaSpec,
)
from ai_converter.schema.source_spec_normalizer import normalize_source_schema_spec
from ai_converter.schema.target_card_builder import build_target_schema_card


ROOT = Path(__file__).resolve().parents[3]
PROFILE_FIXTURES = ROOT / "tests" / "fixtures" / "profiling"
SCHEMA_FIXTURES = ROOT / "tests" / "fixtures" / "schema"


def test_target_card_builder_exports_nested_pydantic_models() -> None:
    """Verify that nested Pydantic models are exported recursively."""

    module = _load_dsl_schema_module()

    card = build_target_schema_card(module.SchedulingProblem)

    paths = set(_collect_paths(card.model_dump()["fields"]))
    assert "project" in paths
    assert "project.name" in paths
    assert "resources" in paths
    assert "resources.id" in paths
    assert "tasks" in paths
    assert "tasks.dependencies" in paths
    assert "tasks.dependencies.task_id" in paths


def test_target_card_builder_preserves_required_optional_flags() -> None:
    """Verify that required and optional target fields are preserved."""

    module = _load_dsl_schema_module()

    card = build_target_schema_card(module.SchedulingProblem)
    fields = _field_map(card.model_dump()["fields"])

    assert fields["problem_id"]["required"] is True
    assert fields["description"]["required"] is False
    assert fields["project"]["required"] is True
    assert fields["project.name"]["required"] is True
    assert fields["tasks.name"]["required"] is False


def test_target_card_builder_extracts_descriptions_and_enums() -> None:
    """Verify that field descriptions and enum values are exported."""

    module = _load_dsl_schema_module()

    card = build_target_schema_card(module.SchedulingProblem)
    fields = _field_map(card.model_dump()["fields"])

    assert fields["domain"]["enum_values"] == ["cluster", "rcpsp"]
    assert "Предметная область" in fields["domain"]["description"]
    assert "Уникальный ID" in fields["problem_id"]["description"]


def test_evidence_packer_respects_budget() -> None:
    """Verify that evidence packing stays within the requested budget."""

    report = build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=4)

    packed = pack_profile_evidence(report, budget=700, mode="compact")

    assert packed.estimated_size <= 700
    assert packed.mode == "compact"
    assert packed.truncated is True


def test_evidence_packer_keeps_high_value_paths() -> None:
    """Verify that evidence packing keeps structurally valuable paths."""

    report = build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=4)

    packed = pack_profile_evidence(report, budget=1400, mode="balanced")
    packed_paths = {field.path for field in packed.fields}

    assert "owner.name" in packed_paths
    assert "tasks[].id" in packed_paths
    assert any(sample.covered_paths for sample in packed.samples)


def test_source_spec_aggregator_merges_aliases_and_confidence() -> None:
    """Verify that candidate aggregation merges aliases and confidence."""

    candidates = [SourceSchemaSpec.model_validate(item) for item in json.loads((SCHEMA_FIXTURES / "source_candidates.json").read_text(encoding="utf-8"))]
    assert all(candidate.version == SOURCE_SCHEMA_SPEC_VERSION for candidate in candidates)

    merged = merge_source_schema_candidates(candidates)

    assert len(merged.fields) == 1
    field = merged.fields[0]
    assert field.semantic_name == "task_name"
    assert field.aliases == ["task_name", "taskname"]
    assert field.examples == ["Execution", "Planning"]
    assert field.confidence == 0.8


def test_source_schema_spec_parses_legacy_payload_without_version() -> None:
    """Verify that legacy payloads still parse and materialize the current version."""

    payload = {
        "source_name": "legacy",
        "source_format": "json",
        "root_type": "list",
        "schema_fingerprint": "legacy-fingerprint",
        "fields": [
            {
                "path": "task_id",
                "semantic_name": "task_id",
                "dtype": "str",
            }
        ],
    }

    parsed = SourceSchemaSpec.model_validate(payload)

    assert parsed.version == SOURCE_SCHEMA_SPEC_VERSION
    assert parsed.canonical_payload()["version"] == SOURCE_SCHEMA_SPEC_VERSION


def test_source_schema_spec_json_schema_exposes_version_field() -> None:
    """Verify that the public JSON schema includes the explicit version marker."""

    schema = SourceSchemaSpec.model_json_schema()

    assert "version" in schema["properties"]
    assert schema["properties"]["version"]["default"] == SOURCE_SCHEMA_SPEC_VERSION


def test_source_schema_spec_canonical_payload_includes_explicit_version() -> None:
    """Verify that the canonical payload exposes the artifact version marker."""

    spec = SourceSchemaSpec(
        source_name="candidate",
        source_format="json",
        root_type="list",
        fields=[SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str")],
    )

    payload = spec.canonical_payload()

    assert spec.version == SOURCE_SCHEMA_SPEC_VERSION
    assert payload["version"] == SOURCE_SCHEMA_SPEC_VERSION
    assert list(payload.keys())[:2] == ["version", "source_name"]


def test_source_spec_normalizer_is_deterministic() -> None:
    """Verify that source-spec normalization is input-order independent."""

    first = SourceSchemaSpec(
        source_name="candidate",
        source_format="json",
        root_type="list",
        fields=[
            SourceFieldSpec(
                path="Task Name",
                semantic_name="Task Name",
                dtype="STR",
                aliases=["TaskName", "task_name"],
                examples=["Beta", "Alpha"],
                confidence=0.4,
            ),
            SourceFieldSpec(
                path="duration_days",
                semantic_name="Duration Days",
                dtype="INT",
                aliases=["DurationDays"],
                examples=["5"],
                confidence=0.6,
            ),
        ],
    )
    second = SourceSchemaSpec(
        source_name="candidate",
        source_format="json",
        root_type="list",
        fields=list(reversed(first.fields)),
    )

    assert normalize_source_schema_spec(first).canonical_payload() == normalize_source_schema_spec(second).canonical_payload()


def _load_dsl_schema_module():
    """Load the external DSL schema module directly from disk for tests.

    Returns:
        Imported DSL schema module used by the target-card tests.
    """

    module_path = ROOT / "dsl-core" / "dsl_schema.py"
    spec = importlib.util.spec_from_file_location("task02_dsl_schema", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load dsl_schema module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_paths(fields: list[dict]) -> list[str]:
    """Collect flattened target-card paths from nested field dictionaries.

    Args:
        fields: Nested target-card field payloads to flatten.

    Returns:
        Flattened list of field paths.
    """

    result: list[str] = []
    for field in fields:
        result.append(field["path"])
        result.extend(_collect_paths(field["children"]))
    return result


def _field_map(fields: list[dict]) -> dict[str, dict]:
    """Map flattened target-card field dictionaries by path.

    Args:
        fields: Nested target-card field payloads to index.

    Returns:
        Field payloads keyed by canonical path.
    """

    return {path: field for field in fields for path, field in _flatten_field(field)}


def _flatten_field(field: dict) -> list[tuple[str, dict]]:
    """Flatten one nested target-card field tree into path-field pairs.

    Args:
        field: Nested target-card field payload to flatten.

    Returns:
        Ordered path-field pairs for the field subtree.
    """

    pairs = [(field["path"], field)]
    for child in field["children"]:
        pairs.extend(_flatten_field(child))
    return pairs
