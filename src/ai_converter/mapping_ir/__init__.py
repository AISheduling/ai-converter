"""Public exports for MappingIR models, validation, ranking, and synthesis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import (
    ConditionClause,
    MappingIR,
    MappingStep,
    SourceReference,
    StepOperation,
    SUPPORTED_OPERATION_KINDS,
    TargetAssignment,
)
from .ranker import RankedCandidate, evaluate_candidate, rank_mapping_candidates, select_best_candidate
from .validator import MappingIRValidator, ValidationIssue, ValidationResult, flatten_target_paths

if TYPE_CHECKING:
    from .repair import RepairCase, build_repair_prompt
    from .synthesizer import MappingCandidateRecord, MappingSynthesizer, MappingSynthesisResult

__all__ = [
    "ConditionClause",
    "MappingIR",
    "MappingIRValidator",
    "MappingStep",
    "RankedCandidate",
    "SourceReference",
    "SUPPORTED_OPERATION_KINDS",
    "StepOperation",
    "TargetAssignment",
    "ValidationIssue",
    "ValidationResult",
    "evaluate_candidate",
    "flatten_target_paths",
    "rank_mapping_candidates",
    "select_best_candidate",
    "RepairCase",
    "build_repair_prompt",
    "MappingCandidateRecord",
    "MappingSynthesizer",
    "MappingSynthesisResult",
]


def __getattr__(name: str) -> Any:
    """Resolve heavier exports lazily to avoid package import cycles.

    Args:
        name: Export name requested from the package namespace.

    Returns:
        Lazily imported object for the requested name.

    Raises:
        AttributeError: If the requested export is unknown.
    """

    if name in {"RepairCase", "build_repair_prompt"}:
        from .repair import RepairCase, build_repair_prompt

        values = {
            "RepairCase": RepairCase,
            "build_repair_prompt": build_repair_prompt,
        }
        return values[name]
    if name in {"MappingCandidateRecord", "MappingSynthesizer", "MappingSynthesisResult"}:
        from .synthesizer import MappingCandidateRecord, MappingSynthesizer, MappingSynthesisResult

        values = {
            "MappingCandidateRecord": MappingCandidateRecord,
            "MappingSynthesizer": MappingSynthesizer,
            "MappingSynthesisResult": MappingSynthesisResult,
        }
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Return stable module exports for interactive and inspection tooling."""

    return sorted(set(globals()) | set(__all__))
