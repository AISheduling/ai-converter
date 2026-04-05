"""Deterministic semantic assertions for compiled converter outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.compiler.runtime_ops import evaluate_expression, get_path_value


class SemanticAssertion(BaseModel):
    """One semantic assertion applied to a converted output payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["equals", "enum_mapping", "unit_conversion", "predicate"] = "equals"
    target_path: str
    source_path: str | None = None
    expected: Any = None
    mapping: dict[str, Any] = Field(default_factory=dict)
    factor: float | None = None
    expression: str | None = None
    description: str | None = None


class SemanticIssue(BaseModel):
    """Machine-readable semantic validation issue."""

    model_config = ConfigDict(extra="forbid")

    assertion_name: str
    code: str
    target_path: str
    message: str
    expected: Any = None
    actual: Any = None


class SemanticValidationResult(BaseModel):
    """Structured result of evaluating semantic assertions."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[SemanticIssue] = Field(default_factory=list)


def validate_semantic_output(
    source_record: dict[str, Any],
    converted_payload: dict[str, Any],
    assertions: list[SemanticAssertion],
) -> SemanticValidationResult:
    """Evaluate semantic assertions over one source/output pair.

    Args:
        source_record: Source-side input record consumed by the converter.
        converted_payload: Target-side dictionary produced by the converter.
        assertions: Semantic assertions to evaluate.

    Returns:
        Structured semantic validation result.
    """

    issues: list[SemanticIssue] = []
    for assertion in assertions:
        actual = get_path_value(converted_payload, assertion.target_path)
        if assertion.kind == "predicate":
            predicate_ok = bool(_expected_value(assertion, source_record, converted_payload, actual))
            if predicate_ok:
                continue
            issues.append(
                SemanticIssue(
                    assertion_name=assertion.name,
                    code="semantic_predicate_failed",
                    target_path=assertion.target_path,
                    message=assertion.description or f"semantic assertion {assertion.name!r} failed",
                    expected=True,
                    actual=False,
                )
            )
            continue
        expected = _expected_value(assertion, source_record, converted_payload, actual)
        if actual == expected:
            continue
        issues.append(
            SemanticIssue(
                assertion_name=assertion.name,
                code=f"semantic_{assertion.kind}_mismatch",
                target_path=assertion.target_path,
                message=assertion.description or f"semantic assertion {assertion.name!r} failed",
                expected=expected,
                actual=actual,
            )
        )

    return SemanticValidationResult(valid=not issues, issues=issues)


def _expected_value(
    assertion: SemanticAssertion,
    source_record: dict[str, Any],
    converted_payload: dict[str, Any],
    actual: Any,
) -> Any:
    """Compute the expected value for one semantic assertion.

    Args:
        assertion: Semantic assertion being evaluated.
        source_record: Source-side input record.
        converted_payload: Target-side output payload.
        actual: Actual resolved target-side value.

    Returns:
        Expected semantic value for the assertion.
    """

    if assertion.kind == "equals":
        if assertion.expected is not None:
            return assertion.expected
        return get_path_value(source_record, assertion.source_path or assertion.target_path)

    if assertion.kind == "enum_mapping":
        source_value = get_path_value(source_record, assertion.source_path or assertion.target_path)
        return assertion.mapping.get(str(source_value), source_value)

    if assertion.kind == "unit_conversion":
        source_value = get_path_value(source_record, assertion.source_path or assertion.target_path)
        if source_value is None or assertion.factor is None:
            return source_value
        return float(source_value) * assertion.factor

    if assertion.kind == "predicate":
        if assertion.expression is None:
            return True
        return bool(
            evaluate_expression(
                assertion.expression,
                {
                    "actual": actual,
                    "source": source_record,
                    "target": converted_payload,
                },
            )
        )

    raise ValueError(f"unsupported semantic assertion kind {assertion.kind!r}")
