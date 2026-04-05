"""Deterministic ranking helpers for MappingIR candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from ai_converter.schema import SourceSchemaSpec, TargetSchemaCard

from .models import MappingIR
from .validator import (
    MappingIRValidator,
    ValidationResult,
    flatten_assignable_target_paths,
)


@dataclass(slots=True)
class RankedCandidate:
    """One scored MappingIR candidate after validation and coverage analysis.

    Attributes:
        candidate: Mapping candidate, or ``None`` when parsing failed.
        validation: Validation result associated with the candidate.
        coverage_paths: Target paths covered by assignments in the candidate.
        coverage_ratio: Share of known target paths covered by the candidate.
        score: Deterministic ranking score used for selection.
        fingerprint: Stable candidate fingerprint used for tie-breaking.
    """

    candidate: MappingIR | None
    validation: ValidationResult
    coverage_paths: list[str]
    coverage_ratio: float
    score: float
    fingerprint: str


def evaluate_candidate(
    candidate: MappingIR | None,
    *,
    validation: ValidationResult,
    target_schema: TargetSchemaCard | None = None,
) -> RankedCandidate:
    """Score one mapping candidate from validation and target coverage.

    Args:
        candidate: Mapping candidate to score, or ``None`` if parsing failed.
        validation: Validation result already computed for the candidate.
        target_schema: Optional target schema used for coverage scoring.

    Returns:
        A scored ``RankedCandidate`` record.
    """

    coverage_paths: list[str] = []
    coverage_ratio = 0.0
    fingerprint = _candidate_fingerprint(candidate)
    if candidate is not None:
        coverage_paths = _coverage_paths(candidate, target_schema=target_schema)
        if target_schema is not None:
            target_paths = flatten_assignable_target_paths(target_schema)
            if target_paths:
                coverage_ratio = len(coverage_paths) / len(target_paths)
        elif candidate.assignments:
            coverage_ratio = 1.0

    score = (
        (1000.0 if validation.valid else 0.0)
        + (coverage_ratio * 100.0)
        + len(coverage_paths)
        - (len(validation.issues) * 25.0)
    )
    return RankedCandidate(
        candidate=candidate,
        validation=validation,
        coverage_paths=coverage_paths,
        coverage_ratio=coverage_ratio,
        score=score,
        fingerprint=fingerprint,
    )


def rank_mapping_candidates(
    candidates: Iterable[MappingIR],
    *,
    source_schema: SourceSchemaSpec | None = None,
    target_schema: TargetSchemaCard | None = None,
    validator: MappingIRValidator | None = None,
) -> list[RankedCandidate]:
    """Validate and deterministically rank mapping candidates.

    Args:
        candidates: Mapping candidates to rank.
        source_schema: Optional source schema used during validation.
        target_schema: Optional target schema used during validation and scoring.
        validator: Optional validator instance to reuse.

    Returns:
        Ranked candidate list sorted from best to worst.
    """

    mapping_validator = validator or MappingIRValidator()
    ranked = [
        evaluate_candidate(
            candidate,
            validation=mapping_validator.validate(candidate, source_schema=source_schema, target_schema=target_schema),
            target_schema=target_schema,
        )
        for candidate in candidates
    ]
    return sorted(ranked, key=_sort_key)


def select_best_candidate(
    candidates: Iterable[MappingIR],
    *,
    source_schema: SourceSchemaSpec | None = None,
    target_schema: TargetSchemaCard | None = None,
    validator: MappingIRValidator | None = None,
) -> RankedCandidate | None:
    """Select the best deterministic mapping candidate from an iterable.

    Args:
        candidates: Mapping candidates to rank and select from.
        source_schema: Optional source schema used during validation.
        target_schema: Optional target schema used during validation and scoring.
        validator: Optional validator instance to reuse.

    Returns:
        The top-ranked candidate, or ``None`` if no candidates were provided.
    """

    ranked = rank_mapping_candidates(
        candidates,
        source_schema=source_schema,
        target_schema=target_schema,
        validator=validator,
    )
    return ranked[0] if ranked else None


def _coverage_paths(candidate: MappingIR, *, target_schema: TargetSchemaCard | None) -> list[str]:
    """Collect sorted target paths covered by one candidate.

    Args:
        candidate: Mapping candidate to inspect.
        target_schema: Optional target schema used to filter valid paths.

    Returns:
        Sorted list of covered target paths.
    """

    target_paths = (
        flatten_assignable_target_paths(target_schema)
        if target_schema is not None
        else None
    )
    covered = {
        assignment.target_path
        for assignment in candidate.assignments
        if target_paths is None or assignment.target_path in target_paths
    }
    return sorted(covered)


def _candidate_fingerprint(candidate: MappingIR | None) -> str:
    """Build a stable fingerprint for deterministic tie-breaking.

    Args:
        candidate: Mapping candidate to fingerprint.

    Returns:
        Stable hex fingerprint string.
    """

    if candidate is None:
        return "~missing-candidate"
    payload = json.dumps(candidate.canonical_payload(), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sort_key(candidate: RankedCandidate) -> tuple[float, str]:
    """Build deterministic sort key for ranked candidates.

    Args:
        candidate: Ranked candidate to sort.

    Returns:
        Tuple sorting highest score first and fingerprint second.
    """

    return -candidate.score, candidate.fingerprint
