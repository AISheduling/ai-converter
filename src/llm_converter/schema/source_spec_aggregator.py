"""Deterministic post-processing for multiple source-schema candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .source_spec_models import SourceFieldSpec, SourceSchemaSpec
from .source_spec_normalizer import normalize_source_schema_spec


def merge_source_schema_candidates(candidates: Iterable[SourceSchemaSpec]) -> SourceSchemaSpec:
    """Merge multiple source-schema candidates into one deterministic schema."""

    normalized_candidates = [normalize_source_schema_spec(candidate) for candidate in candidates]
    if not normalized_candidates:
        raise ValueError("at least one source schema candidate is required")

    merged_fields: list[_FieldCluster] = []
    for candidate in normalized_candidates:
        for field in candidate.fields:
            cluster = next((item for item in merged_fields if item.matches(field)), None)
            if cluster is None:
                merged_fields.append(_FieldCluster([field]))
            else:
                cluster.fields.append(field)

    merged_spec = normalized_candidates[0].model_copy(
        update={
            "fields": [
                cluster.build_field()
                for cluster in sorted(merged_fields, key=lambda item: item.sort_key())
            ]
        }
    )
    return normalize_source_schema_spec(merged_spec)


@dataclass
class _FieldCluster:
    """Mutable cluster used while merging source field candidates."""

    fields: list[SourceFieldSpec]

    def matches(self, other: SourceFieldSpec) -> bool:
        """Return whether another field belongs to this cluster."""

        current = self.build_field()
        if current.path == other.path:
            return True
        if current.semantic_name == other.semantic_name:
            return True
        return bool(set(current.aliases) & set(other.aliases))

    def sort_key(self) -> tuple[str, str]:
        """Return deterministic sorting key for the merged field."""

        field = self.build_field()
        return (field.semantic_name, field.path)

    def build_field(self) -> SourceFieldSpec:
        """Build the merged field view for this cluster."""

        paths = Counter(field.path for field in self.fields)
        semantic_names = Counter(field.semantic_name for field in self.fields)
        dtypes = Counter(field.dtype for field in self.fields)
        cardinalities = Counter(field.cardinality for field in self.fields)
        descriptions = [field.description for field in self.fields if field.description]
        units = Counter(field.unit for field in self.fields if field.unit)
        nullable = any(field.nullable for field in self.fields)
        aliases = sorted({alias for field in self.fields for alias in field.aliases})
        examples = sorted({example for field in self.fields for example in field.examples})
        confidence = sum(field.confidence for field in self.fields) / len(self.fields)

        return SourceFieldSpec(
            path=_pick_counter_value(paths),
            semantic_name=_pick_counter_value(semantic_names),
            description=max(descriptions, key=len) if descriptions else None,
            dtype=_pick_counter_value(dtypes),
            cardinality=_pick_counter_value(cardinalities),
            nullable=nullable,
            aliases=aliases,
            unit=_pick_counter_value(units) if units else None,
            examples=examples[:5],
            confidence=round(confidence, 4),
        )


def _pick_counter_value(counter: Counter[str | None]) -> str:
    """Select the most frequent counter value with deterministic tie-breaking."""

    ranked = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    value = ranked[0][0]
    if value is None:
        raise ValueError("expected a non-null counter value")
    return value
