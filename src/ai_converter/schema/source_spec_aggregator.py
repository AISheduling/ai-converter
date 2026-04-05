"""Deterministic post-processing for multiple source-schema candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable, Literal, TypeVar

from .source_spec_models import SourceFieldSpec, SourceSchemaSpec
from .source_spec_normalizer import normalize_source_schema_spec

_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")
CounterValueT = TypeVar("CounterValueT", bound=str)


def merge_source_schema_candidates(candidates: Iterable[SourceSchemaSpec]) -> SourceSchemaSpec:
    """Merge multiple source-schema candidates into one deterministic schema.

    Args:
        candidates: Source-schema candidates to normalize and merge.

    Returns:
        Deterministic merged source schema candidate.
    """

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
        """Return whether another field belongs to this cluster.

        Args:
            other: Source field candidate to compare against the cluster.

        Returns:
            `True` when the field should merge into this cluster.
        """

        current = self.build_field()
        if current.path == other.path:
            return True
        return self._has_strong_alias_overlap(current, other)

    @staticmethod
    def _has_strong_alias_overlap(current: SourceFieldSpec, other: SourceFieldSpec) -> bool:
        """Return whether the fields share alias evidence beyond semantic labels.

        `semantic_name` is a hint about meaning, not a stable identity on its own.
        When two paths differ, only stronger alias overlap should merge them.
        """

        shared_aliases = set(current.aliases) & set(other.aliases)
        weak_aliases = {current.semantic_name, other.semantic_name}
        current_leaf = _canonical_path_leaf(current.path)
        other_leaf = _canonical_path_leaf(other.path)
        if current_leaf == other_leaf:
            weak_aliases.add(current_leaf)
        return bool(shared_aliases - weak_aliases)

    def sort_key(self) -> tuple[str, str]:
        """Return deterministic sorting key for the merged field.

        Returns:
            Tuple used to sort merged fields deterministically.
        """

        field = self.build_field()
        return field.semantic_name, field.path

    def build_field(self) -> SourceFieldSpec:
        """Build the merged field view for this cluster.

        Returns:
            Merged source field synthesized from the clustered candidates.
        """

        paths = Counter(field.path for field in self.fields)
        semantic_names = Counter(field.semantic_name for field in self.fields)
        dtypes = Counter(field.dtype for field in self.fields)
        cardinalities: Counter[Literal["one", "many"]] = Counter(
            field.cardinality for field in self.fields
        )
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


def _pick_counter_value(counter: Counter[CounterValueT]) -> CounterValueT:
    """Select the most frequent counter value with deterministic tie-breaking.

    Args:
        counter: Counter whose most stable value should be selected.

    Returns:
        Most frequent counter value after deterministic tie-breaking.
    """

    ranked = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    value = ranked[0][0]
    return value


def _canonical_path_leaf(path: str) -> str:
    """Return the canonical terminal token for a source path."""

    leaf = path.split(".")[-1].replace("[]", "")
    collapsed = _TOKEN_PATTERN.sub("_", leaf.strip().lower())
    return collapsed.strip("_")
