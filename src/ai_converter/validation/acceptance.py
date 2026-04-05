"""Acceptance orchestration for compiled converter validation suites."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .semantic import SemanticAssertion, SemanticIssue, validate_semantic_output
from .structural import StructuralIssue, validate_structural_output


class AcceptanceCase(BaseModel):
    """One fixture case executed by the acceptance suite."""

    model_config = ConfigDict(extra="forbid")

    name: str
    record: dict[str, Any]
    assertions: list[SemanticAssertion] = Field(default_factory=list)


class AcceptanceCaseReport(BaseModel):
    """Detailed acceptance report for one fixture case."""

    model_config = ConfigDict(extra="forbid")

    name: str
    execution_success: bool
    structural_validity: bool
    semantic_validity: bool
    output: dict[str, Any] | None = None
    execution_error: str | None = None
    structural_issues: list[StructuralIssue] = Field(default_factory=list)
    semantic_issues: list[SemanticIssue] = Field(default_factory=list)


class AcceptanceReport(BaseModel):
    """Aggregate acceptance result across a fixture dataset."""

    model_config = ConfigDict(extra="forbid")

    execution_success: bool
    structural_validity: bool
    semantic_validity: bool
    coverage: float
    repair_iterations: int = 0
    compiler_error: str | None = None
    cases: list[AcceptanceCaseReport] = Field(default_factory=list)


def run_acceptance_suite(
    converter: Callable[[dict[str, Any]], dict[str, Any]],
    dataset: list[AcceptanceCase],
    target_model: type[BaseModel],
    *,
    repair_iterations: int = 0,
) -> AcceptanceReport:
    """Run the acceptance workflow for one compiled converter.

    Args:
        converter: Callable converter entry point that accepts one source record.
        dataset: Fixture cases executed against the converter.
        target_model: Pydantic target model used for structural validation.
        repair_iterations: Current repair-loop iteration count.

    Returns:
        Unified acceptance report across the dataset.
    """

    case_reports: list[AcceptanceCaseReport] = []
    for case in dataset:
        case_reports.append(_run_case(converter, case, target_model))

    total_cases = len(case_reports)
    passing_cases = sum(
        1
        for report in case_reports
        if report.execution_success and report.structural_validity and report.semantic_validity
    )
    coverage = 0.0 if total_cases == 0 else passing_cases / total_cases

    return AcceptanceReport(
        execution_success=all(report.execution_success for report in case_reports),
        structural_validity=all(report.structural_validity for report in case_reports),
        semantic_validity=all(report.semantic_validity for report in case_reports),
        coverage=coverage,
        repair_iterations=repair_iterations,
        cases=case_reports,
    )


def _run_case(
    converter: Callable[[dict[str, Any]], dict[str, Any]],
    case: AcceptanceCase,
    target_model: type[BaseModel],
) -> AcceptanceCaseReport:
    """Run one acceptance fixture case.

    Args:
        converter: Compiled converter entry point.
        case: Fixture case to execute.
        target_model: Pydantic target model used for structural validation.

    Returns:
        Detailed case report with execution, structural, and semantic outcomes.
    """

    try:
        output = converter(case.record)
    except Exception as exc:
        return AcceptanceCaseReport(
            name=case.name,
            execution_success=False,
            structural_validity=False,
            semantic_validity=False,
            execution_error=str(exc),
        )

    structural = validate_structural_output(output, target_model)
    semantic = validate_semantic_output(case.record, output, case.assertions)
    return AcceptanceCaseReport(
        name=case.name,
        execution_success=True,
        structural_validity=structural.valid,
        semantic_validity=semantic.valid,
        output=output,
        structural_issues=structural.issues,
        semantic_issues=semantic.issues,
    )
