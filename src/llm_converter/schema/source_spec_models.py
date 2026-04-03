"""Pydantic models describing normalized source-schema candidates."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceFieldSpec(BaseModel):
    """Canonical description of one source field inferred from profiling or LLM output."""

    path: str
    semantic_name: str
    description: str | None = None
    dtype: str
    cardinality: Literal["one", "many"] = "one"
    nullable: bool = False
    aliases: list[str] = Field(default_factory=list)
    unit: str | None = None
    examples: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SourceSchemaSpec(BaseModel):
    """A deterministic schema-first view of the profiled L0 input."""

    source_name: str
    source_format: Literal["csv", "json", "jsonl"]
    root_type: Literal["rows", "object", "list"]
    schema_fingerprint: str | None = None
    fields: list[SourceFieldSpec] = Field(default_factory=list)
