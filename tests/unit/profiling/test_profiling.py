"""Focused unit tests for deterministic L0 profiling."""

from __future__ import annotations

import json
from pathlib import Path

from llm_converter.profiling.csv_profiler import profile_csv
from llm_converter.profiling.json_profiler import profile_json
from llm_converter.profiling.loaders import LoadedInput
from llm_converter.profiling.report_builder import build_profile_report
from llm_converter.profiling.sampling import SamplingCandidate, select_representative_samples


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiling"


def _field_map(report):
    """Map field-profile entries by normalized path.

    Args:
        report: Profile report whose fields should be indexed.

    Returns:
        Dictionary of field profiles keyed by normalized path.
    """

    return {field.path: field for field in report.field_profiles}


def _report_without_path(report):
    """Return a serialized report with the source path removed.

    Args:
        report: Profile report to serialize for stable comparison.

    Returns:
        Serialized report payload with the source path cleared.
    """

    payload = report.model_dump()
    payload["source"]["path"] = None
    return payload


def test_csv_profile_detects_columns_and_types() -> None:
    """Verify that CSV profiling captures normalized columns and type hints."""

    report = profile_csv(FIXTURES / "people.csv")

    fields = _field_map(report)
    assert report.record_count == 4
    assert report.source.kind == "csv"
    assert set(fields) >= {"id", "name", "role", "hours", "team"}
    assert report.source.normalized_field_aliases["hours"] == "hours"
    assert [entry.type_name for entry in fields["hours"].observed_types] == ["str"]
    assert fields["id"].candidate_id is True
    assert fields["role"].null_ratio > 0.0


def test_json_profile_flattens_nested_paths() -> None:
    """Verify that nested JSON objects and arrays are flattened into paths."""

    report = profile_json(FIXTURES / "projects.json")

    fields = _field_map(report)
    assert report.source.kind == "json"
    assert "owner.name" in fields
    assert "tasks[]" in fields
    assert "tasks[].id" in fields
    assert "metadata.priority" in fields
    assert fields["tasks[]"].max_array_length == 2


def test_profile_is_stable_under_row_reordering() -> None:
    """Verify that row reordering does not change the normalized profile."""

    original = json.loads((FIXTURES / "projects.json").read_text(encoding="utf-8"))
    reordered = list(reversed(original))

    first_report = build_profile_report(LoadedInput(kind="json", path="first.json", records=original))
    second_report = build_profile_report(LoadedInput(kind="json", path="second.json", records=reordered))

    assert first_report.schema_fingerprint == second_report.schema_fingerprint
    assert _report_without_path(first_report) == _report_without_path(second_report)


def test_sampling_is_deterministic() -> None:
    """Verify that representative sampling is deterministic for fixed inputs."""

    candidates = [
        SamplingCandidate(
            record_id=f"record_{index}",
            data=record,
            paths=frozenset(record),
            rarity_score=1.0 / (index + 1),
            completeness=len(record) / 3.0,
        )
        for index, record in enumerate(
            [
                {"a": 1},
                {"a": 1, "b": 2},
                {"a": 1, "c": 3},
            ]
        )
    ]

    first = select_representative_samples(candidates, max_samples=2)
    second = select_representative_samples(candidates, max_samples=2)

    assert first == second


def test_sampling_prefers_records_with_new_coverage() -> None:
    """Verify that sampling favors records that expand path coverage."""

    candidates = [
        SamplingCandidate(
            record_id="plain",
            data={"a": 1},
            paths=frozenset({"a"}),
            rarity_score=0.5,
            completeness=0.5,
        ),
        SamplingCandidate(
            record_id="broad",
            data={"a": 1, "b": 2, "c": 3},
            paths=frozenset({"a", "b", "c"}),
            rarity_score=1.2,
            completeness=1.0,
        ),
        SamplingCandidate(
            record_id="rare",
            data={"a": 1, "d": 4},
            paths=frozenset({"a", "d"}),
            rarity_score=1.0,
            completeness=0.75,
        ),
    ]

    selected = select_representative_samples(candidates, max_samples=2)

    assert selected[0].record_id == "broad"
    assert selected[1].record_id == "rare"
    assert "d" in selected[1].covered_paths


def test_fingerprint_changes_on_structural_change() -> None:
    """Verify that structural schema changes produce a new fingerprint."""

    base_records = [{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}]
    changed_records = [{"id": "1", "name": "alpha", "status": "active"}, {"id": "2", "name": "beta"}]

    base_report = build_profile_report(LoadedInput(kind="json", path="base.json", records=base_records))
    changed_report = build_profile_report(LoadedInput(kind="json", path="changed.json", records=changed_records))

    assert base_report.schema_fingerprint != changed_report.schema_fingerprint


def test_fingerprint_does_not_change_on_value_order_change() -> None:
    """Verify that record ordering alone does not change the fingerprint."""

    first_records = [{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}]
    second_records = list(reversed(first_records))

    first_report = build_profile_report(LoadedInput(kind="json", path="first.json", records=first_records))
    second_report = build_profile_report(LoadedInput(kind="json", path="second.json", records=second_records))

    assert first_report.schema_fingerprint == second_report.schema_fingerprint
