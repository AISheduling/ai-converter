"""Deterministic normalization helpers for source-schema candidates."""

from __future__ import annotations

import re

from .source_spec_models import SourceFieldSpec, SourceSchemaSpec

_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_source_schema_spec(spec: SourceSchemaSpec) -> SourceSchemaSpec:
    """Return a deterministic normalized copy of a source schema candidate."""

    normalized_fields = [normalize_source_field(field) for field in spec.fields]
    normalized_fields.sort(key=lambda field: (_canonical_identifier(field.semantic_name), field.path))
    return spec.model_copy(update={"fields": normalized_fields})


def normalize_source_field(field: SourceFieldSpec) -> SourceFieldSpec:
    """Return a normalized copy of a source field candidate."""

    normalized_path = field.path.strip()
    semantic_name = _canonical_identifier(field.semantic_name or _path_leaf(normalized_path))
    aliases = sorted(
        {
            alias
            for alias in (
                [_canonical_identifier(semantic_name), _canonical_identifier(_path_leaf(normalized_path))]
                + [_canonical_identifier(value) for value in field.aliases]
            )
            if alias
        }
    )
    examples = sorted({example.strip() for example in field.examples if example.strip()})
    normalized_cardinality = "many" if normalized_path.endswith("[]") or field.cardinality == "many" else "one"
    return field.model_copy(
        update={
            "path": normalized_path,
            "semantic_name": semantic_name,
            "aliases": aliases,
            "examples": examples,
            "cardinality": normalized_cardinality,
            "dtype": field.dtype.strip().lower(),
            "unit": field.unit.strip() if field.unit else None,
        }
    )


def _path_leaf(path: str) -> str:
    """Return the terminal token for a normalized source path."""

    leaf = path.split(".")[-1]
    return leaf.replace("[]", "") or "value"


def _canonical_identifier(value: str) -> str:
    """Convert free-form text into a stable snake_case identifier."""

    collapsed = _TOKEN_PATTERN.sub("_", value.strip().lower())
    return collapsed.strip("_")
