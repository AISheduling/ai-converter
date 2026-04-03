"""Focused unit tests for schema contracts and evidence packing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from llm_converter.profiling.report_builder import build_profile_report
from llm_converter.schema.evidence_packer import pack_profile_evidence
from llm_converter.schema.source_spec_aggregator import merge_source_schema_candidates
from llm_converter.schema.source_spec_models import SourceFieldSpec, SourceSchemaSpec
from llm_converter.schema.source_spec_normalizer import normalize_source_schema_spec
from llm_converter.schema.target_card_builder import build_target_schema_card


ROOT = Path(__file__).resolve().parents[3]
PROFILE_FIXTURES = ROOT / "tests" / "fixtures" / "profiling"
SCHEMA_FIXTURES = ROOT / "tests" / "fixtures" / "schema"


def test_target_card_builder_exports_nested_pydantic_models() -> None:
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
    module = _load_dsl_schema_module()

    card = build_target_schema_card(module.SchedulingProblem)
    fields = _field_map(card.model_dump()["fields"])

    assert fields["problem_id"]["required"] is True
    assert fields["description"]["required"] is False
    assert fields["project"]["required"] is True
    assert fields["project.name"]["required"] is True
    assert fields["tasks.name"]["required"] is False


def test_target_card_builder_extracts_descriptions_and_enums() -> None:
    module = _load_dsl_schema_module()

    card = build_target_schema_card(module.SchedulingProblem)
    fields = _field_map(card.model_dump()["fields"])

    assert fields["domain"]["enum_values"] == ["cluster", "rcpsp"]
    assert "Предметная область" in fields["domain"]["description"]
    assert "Уникальный ID" in fields["problem_id"]["description"]


def test_evidence_packer_respects_budget() -> None:
    report = build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=4)

    packed = pack_profile_evidence(report, budget=700, mode="compact")

    assert packed.estimated_size <= 700
    assert packed.mode == "compact"
    assert packed.truncated is True


def test_evidence_packer_keeps_high_value_paths() -> None:
    report = build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=4)

    packed = pack_profile_evidence(report, budget=1400, mode="balanced")
    packed_paths = {field.path for field in packed.fields}

    assert "owner.name" in packed_paths
    assert "tasks[].id" in packed_paths
    assert any(sample.covered_paths for sample in packed.samples)


def test_source_spec_aggregator_merges_aliases_and_confidence() -> None:
    candidates = [SourceSchemaSpec.model_validate(item) for item in json.loads((SCHEMA_FIXTURES / "source_candidates.json").read_text(encoding="utf-8"))]

    merged = merge_source_schema_candidates(candidates)

    assert len(merged.fields) == 1
    field = merged.fields[0]
    assert field.semantic_name == "task_name"
    assert field.aliases == ["task_name", "taskname"]
    assert field.examples == ["Execution", "Planning"]
    assert field.confidence == 0.8


def test_source_spec_normalizer_is_deterministic() -> None:
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

    assert normalize_source_schema_spec(first).model_dump() == normalize_source_schema_spec(second).model_dump()


def _load_dsl_schema_module():
    module_path = ROOT / "dsl-core" / "dsl_schema.py"
    spec = importlib.util.spec_from_file_location("task02_dsl_schema", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load dsl_schema module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_paths(fields: list[dict]) -> list[str]:
    result: list[str] = []
    for field in fields:
        result.append(field["path"])
        result.extend(_collect_paths(field["children"]))
    return result


def _field_map(fields: list[dict]) -> dict[str, dict]:
    return {path: field for field in fields for path, field in _flatten_field(field)}


def _flatten_field(field: dict) -> list[tuple[str, dict]]:
    pairs = [(field["path"], field)]
    for child in field["children"]:
        pairs.extend(_flatten_field(child))
    return pairs
