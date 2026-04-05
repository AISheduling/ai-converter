"""Structural validation helpers for compiled converter outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StructuralIssue(BaseModel):
    """Machine-readable structural validation issue."""

    model_config = ConfigDict(extra="forbid")

    code: str
    path: str
    message: str
    input_value: Any = None


class StructuralValidationResult(BaseModel):
    """Structured result of validating one converter output payload."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[StructuralIssue] = Field(default_factory=list)
    validated_output: dict[str, Any] | None = None


def validate_structural_output(payload: dict[str, Any], target_model: type[BaseModel]) -> StructuralValidationResult:
    """Validate one converter payload against a target Pydantic model.

    Args:
        payload: Target-side dictionary produced by the compiled converter.
        target_model: Pydantic model used as the structural contract.

    Returns:
        Structured structural validation result with machine-readable issues.
    """

    try:
        validated = target_model.model_validate(payload)
    except ValidationError as exc:
        issues = [
            StructuralIssue(
                code=error["type"],
                path=".".join(str(part) for part in error["loc"]) or "$",
                message=error["msg"],
                input_value=error.get("input"),
            )
            for error in exc.errors(include_input=True)
        ]
        return StructuralValidationResult(valid=False, issues=issues)

    return StructuralValidationResult(
        valid=True,
        validated_output=validated.model_dump(mode="json"),
    )
