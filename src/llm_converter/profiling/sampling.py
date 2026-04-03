"""Deterministic representative sampling for profiled records."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from .models import SampleRecord


class SamplingCandidate(BaseModel):
    """Precomputed candidate used by sampling-focused tests and callers."""

    record_id: str
    data: dict[str, Any]
    paths: frozenset[str]
    rarity_score: float = 0.0
    completeness: float = 0.0
    covered_paths: list[str] = Field(default_factory=list)


def select_representative_samples(
    candidates_or_records,
    raw_records: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
    max_samples: int | None = None,
):
    """Select records that maximize coverage and rare-structure exposure."""

    if candidates_or_records and isinstance(candidates_or_records[0], SamplingCandidate):
        effective_limit = max_samples if max_samples is not None else limit
        return _select_from_candidates(candidates_or_records, effective_limit or 3)

    assert raw_records is not None
    effective_limit = limit if limit is not None else max_samples
    return _select_from_flattened(candidates_or_records, raw_records, effective_limit or 3)


def _select_from_flattened(
    flattened_records: list[dict[str, list[Any]]],
    raw_records: list[dict[str, Any]],
    limit: int,
) -> list[SampleRecord]:
    """Select representative samples from flattened records."""

    limit = max(0, min(limit, len(raw_records)))
    if limit == 0:
        return []

    path_counts = Counter()
    typed_path_counts = Counter()
    for flattened in flattened_records:
        for path, values in flattened.items():
            path_counts[path] += 1
            for value in values:
                typed_path_counts[(path, _type_name(value))] += 1

    selected: list[SampleRecord] = []
    covered_paths: set[str] = set()
    chosen_indexes: set[int] = set()
    for _ in range(limit):
        best_index = -1
        best_score = float("-inf")
        best_paths: list[str] = []
        for index, flattened in enumerate(flattened_records):
            if index in chosen_indexes:
                continue
            score, record_paths = _score_record(
                flattened,
                covered_paths=covered_paths,
                path_counts=path_counts,
                typed_path_counts=typed_path_counts,
            )
            if score > best_score or (score == best_score and index < best_index):
                best_index = index
                best_score = score
                best_paths = record_paths
        if best_index < 0:
            break
        chosen_indexes.add(best_index)
        covered_paths.update(best_paths)
        selected.append(
            SampleRecord(
                index=best_index,
                record_id=str(best_index),
                score=best_score,
                covered_paths=best_paths,
                record=raw_records[best_index],
            )
        )
    return selected


def _select_from_candidates(candidates: list[SamplingCandidate], limit: int) -> list[SamplingCandidate]:
    """Select representative candidates from precomputed sampling inputs."""

    effective_limit = max(0, min(limit, len(candidates)))
    selected: list[SamplingCandidate] = []
    covered_paths: set[str] = set()
    remaining = list(candidates)
    for _ in range(effective_limit):
        best: SamplingCandidate | None = None
        best_score = float("-inf")
        for candidate in remaining:
            new_paths = sorted(path for path in candidate.paths if path not in covered_paths)
            score = len(new_paths) + candidate.completeness + candidate.rarity_score
            if score > best_score or (
                score == best_score
                and best is not None
                and candidate.record_id < best.record_id
            ) or best is None:
                best = candidate
                best_score = score
        if best is None:
            break
        remaining = [candidate for candidate in remaining if candidate.record_id != best.record_id]
        covered = sorted(path for path in best.paths if path not in covered_paths)
        covered_paths.update(best.paths)
        selected.append(best.model_copy(update={"covered_paths": covered}))
    return selected


def _score_record(
    flattened: dict[str, list[Any]],
    *,
    covered_paths: set[str],
    path_counts: Counter[str],
    typed_path_counts: Counter[tuple[str, str]],
) -> tuple[float, list[str]]:
    """Score a flattened record by coverage, completeness, and rarity."""

    record_paths = sorted(flattened)
    new_paths = [path for path in record_paths if path not in covered_paths]
    new_path_coverage = float(len(new_paths))

    non_null_values = 0
    rarity_bonus = 0.0
    for path, values in flattened.items():
        for value in values:
            if value is not None:
                non_null_values += 1
            rarity_bonus += 1.0 / typed_path_counts[(path, _type_name(value))]
        rarity_bonus += 1.0 / path_counts[path]
    completeness_bonus = non_null_values / max(1, len(record_paths) or 1)

    return new_path_coverage + completeness_bonus + rarity_bonus, record_paths


def _type_name(value: Any) -> str:
    """Return the normalized sampling type label for a Python value."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "str"
