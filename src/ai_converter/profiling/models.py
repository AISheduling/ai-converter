"""Pydantic models describing normalized profiling inputs and reports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScalarSummary(BaseModel):
    """Summary values for numeric or length-based measurements."""

    min: float | None = None
    max: float | None = None


class ValueCount(BaseModel):
    """Count for a frequently observed scalar value."""

    value: str
    count: int = Field(ge=0)


class ObservedTypeCount(BaseModel):
    """Observed type frequency for one field."""

    type_name: str
    count: int = Field(ge=0)


class FieldProfile(BaseModel):
    """Observed statistics for one normalized path."""

    path: str
    original_names: list[str] = Field(default_factory=list)
    observed_types: list[ObservedTypeCount] = Field(default_factory=list)
    present_ratio: float = Field(ge=0.0, le=1.0)
    null_ratio: float = Field(ge=0.0, le=1.0)
    unique_ratio: float = Field(ge=0.0, le=1.0)
    numeric_range: ScalarSummary | None = None
    length_range: ScalarSummary | None = None
    max_array_length: int | None = None
    top_values: list[ValueCount] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    candidate_id: bool = False


class SampleRecord(BaseModel):
    """One representative record selected for downstream evidence packing."""

    index: int = Field(ge=0)
    record_id: str
    score: float
    covered_paths: list[str] = Field(default_factory=list)
    record: dict[str, Any]


class SourceInfo(BaseModel):
    """Metadata about the original source payload."""

    kind: Literal["csv", "json", "jsonl"]
    path: str | None = None
    normalized_field_aliases: dict[str, str] = Field(default_factory=dict)


class DatasetMetadata(BaseModel):
    """Metadata about the normalized source dataset."""

    source_name: str
    source_format: Literal["csv", "json", "jsonl"]
    root_type: Literal["rows", "object", "list"]
    record_count: int = Field(ge=0)


class ProfileReport(BaseModel):
    """Canonical profiling output."""

    source: SourceInfo
    record_count: int = Field(ge=0)
    metadata: DatasetMetadata
    field_profiles: list[FieldProfile]
    representative_samples: list[SampleRecord]
    schema_fingerprint: str

    @property
    def fields(self) -> list[FieldProfile]:
        """Compatibility alias for profiling report consumers.

        Returns:
            Field profiles from the canonical report payload.
        """

        return self.field_profiles

    @property
    def fingerprint(self) -> str:
        """Compatibility alias for profiling report consumers.

        Returns:
            Stable schema fingerprint for the report.
        """

        return self.schema_fingerprint
