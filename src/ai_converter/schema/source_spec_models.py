"""Pydantic models describing normalized source-schema candidates."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SOURCE_SCHEMA_SPEC_VERSION = "1.0"


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
    """A deterministic schema-first view of the profiled L0 input.

    The serialized artifact contract is versioned at the top level so that
    persisted schema payloads can evolve independently from prompt-template
    versions or surrounding pipeline metadata.
    """

    version: str = SOURCE_SCHEMA_SPEC_VERSION
    source_name: str
    source_format: Literal["csv", "json", "jsonl"]
    root_type: Literal["rows", "object", "list"]
    schema_fingerprint: str | None = None
    fields: list[SourceFieldSpec] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _strip_version(cls, value: str) -> str:
        """Normalize the artifact version marker.

        Args:
            value: Raw version string from the payload.

        Returns:
            The stripped non-empty version string.

        Raises:
            ValueError: If the version is blank after normalization.
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("version must not be blank")
        return normalized

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation of the artifact.

        Returns:
            JSON-compatible payload for deterministic persistence and hashing.
        """

        return self.model_dump(mode="json")
