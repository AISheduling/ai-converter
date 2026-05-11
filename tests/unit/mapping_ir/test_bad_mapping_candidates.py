"""Regression tests for reduced live bad MappingIR candidates."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_converter.mapping_ir import MappingIR, MappingIRValidator


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "bad_mapping_candidates"
EXPECTED_FIXTURES = {
    "default_with_coalesce_expression.json",
    "derive_with_unknown_first_non_null.json",
    "derive_with_non_python_ternary.json",
    "single_surface_status_precondition.json",
    "tags_copy_without_default.json",
}


@pytest.fixture
def fixture_loader() -> Callable[[str], MappingIR]:
    """Load one reduced bad-candidate fixture as a MappingIR program."""

    def load(name: str) -> MappingIR:
        return MappingIR.model_validate_json((FIXTURE_ROOT / name).read_text(encoding="utf-8"))

    return load


def test_bad_candidate_fixture_set_is_offline_and_deterministic() -> None:
    """Verify the reduced fixture set contains no trace or live-service payloads."""

    fixture_names = {path.name for path in FIXTURE_ROOT.glob("*.json")}

    assert fixture_names == EXPECTED_FIXTURES
    for fixture_path in sorted(FIXTURE_ROOT.glob("*.json")):
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, sort_keys=True)

        MappingIR.model_validate(payload)
        assert "raw_text" not in payload
        assert "system_prompt" not in payload
        assert "user_prompt" not in payload
        assert "usage" not in payload
        assert "https://" not in serialized
        assert "api.openai.com" not in serialized
        assert "sk-" not in serialized


@pytest.mark.parametrize(
    ("fixture_name", "expected_code", "expected_message"),
    [
        (
            "default_with_coalesce_expression.json",
            "invalid_arguments",
            "operation 'default' does not support expression, source_refs",
        ),
        (
            "derive_with_unknown_first_non_null.json",
            "invalid_expression",
            "if_defined_then_use_first_non_null",
        ),
        (
            "derive_with_non_python_ternary.json",
            "invalid_expression",
            "invalid expression syntax",
        ),
    ],
)
def test_bad_candidate_validator_rejects_static_failures(
    fixture_loader: Callable[[str], MappingIR],
    fixture_name: str,
    expected_code: str,
    expected_message: str,
) -> None:
    """Verify statically bad live candidates are rejected by MappingIRValidator."""

    program = fixture_loader(fixture_name)

    result = MappingIRValidator().validate(program)

    assert result.valid is False
    issue = next(issue for issue in result.issues if issue.code == expected_code)
    assert expected_message in issue.message


@pytest.mark.parametrize(
    "fixture_name",
    [
        "single_surface_status_precondition.json",
        "tags_copy_without_default.json",
    ],
)
def test_runtime_bad_candidate_fixtures_remain_validator_valid(
    fixture_loader: Callable[[str], MappingIR],
    fixture_name: str,
) -> None:
    """Verify runtime-bad fixtures exercise smoke ranking, not static rejection."""

    result = MappingIRValidator().validate(fixture_loader(fixture_name))

    assert result.valid is True
    assert result.issues == []
