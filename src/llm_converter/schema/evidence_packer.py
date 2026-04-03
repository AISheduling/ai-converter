"""Deterministic evidence packing for profile reports."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from llm_converter.profiling.models import FieldProfile, ProfileReport, SampleRecord

EvidencePackMode = Literal["compact", "balanced", "full"]

_MODE_LIMITS: dict[EvidencePackMode, tuple[int, int]] = {
    "compact": (5, 2),
    "balanced": (8, 3),
    "full": (12, 5),
}


class PackedFieldEvidence(BaseModel):
    """Compact fact bundle for one source path."""

    path: str
    observed_types: list[str] = Field(default_factory=list)
    present_ratio: float
    null_ratio: float
    unique_ratio: float
    candidate_id: bool
    examples: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    max_array_length: int | None = None


class PackedSampleEvidence(BaseModel):
    """Compact fact bundle for one representative sample."""

    index: int
    record_id: str
    covered_paths: list[str] = Field(default_factory=list)
    record: dict


class PackedEvidenceSummary(BaseModel):
    """Global summary facts for a packed profile report."""

    source_format: str
    root_type: str
    record_count: int
    field_count: int
    schema_fingerprint: str


class PackedEvidenceBundle(BaseModel):
    """Deterministic prompt-oriented evidence bundle for LLM stages."""

    mode: EvidencePackMode
    budget: int = Field(gt=0)
    estimated_size: int = Field(default=0, ge=0)
    truncated: bool = False
    format_hint: str | None = None
    summary: PackedEvidenceSummary
    fields: list[PackedFieldEvidence] = Field(default_factory=list)
    samples: list[PackedSampleEvidence] = Field(default_factory=list)


def pack_profile_evidence(
    report: ProfileReport,
    *,
    budget: int = 1800,
    mode: EvidencePackMode = "balanced",
    format_hint: str | None = None,
) -> PackedEvidenceBundle:
    """Pack a profile report into a deterministic budgeted evidence bundle."""

    field_limit, sample_limit = _MODE_LIMITS[mode]
    bundle = PackedEvidenceBundle(
        mode=mode,
        budget=budget,
        format_hint=format_hint,
        summary=PackedEvidenceSummary(
            source_format=report.metadata.source_format,
            root_type=report.metadata.root_type,
            record_count=report.record_count,
            field_count=len(report.field_profiles),
            schema_fingerprint=report.schema_fingerprint,
        ),
    )

    selected_fields = 0
    for field in sorted(report.field_profiles, key=lambda item: (-_field_score(item), item.path)):
        if selected_fields >= field_limit:
            bundle.truncated = True
            break
        candidate = bundle.model_copy(deep=True)
        candidate.fields.append(_pack_field(field))
        candidate.estimated_size = _estimate_size(candidate)
        if candidate.estimated_size > budget and bundle.fields:
            bundle.truncated = True
            continue
        bundle = candidate
        selected_fields += 1

    selected_samples = 0
    for sample in report.representative_samples:
        if selected_samples >= sample_limit:
            bundle.truncated = True
            break
        candidate = bundle.model_copy(deep=True)
        candidate.samples.append(_pack_sample(sample))
        candidate.estimated_size = _estimate_size(candidate)
        if candidate.estimated_size > budget and bundle.samples:
            bundle.truncated = True
            continue
        if candidate.estimated_size > budget and not bundle.samples:
            bundle.truncated = True
            break
        bundle = candidate
        selected_samples += 1

    if not bundle.samples and report.representative_samples:
        bundle = _ensure_at_least_one_sample(bundle, report.representative_samples[0])

    bundle.estimated_size = _estimate_size(bundle)
    return bundle


def _pack_field(field: FieldProfile) -> PackedFieldEvidence:
    """Convert a field profile into compact packed evidence."""

    return PackedFieldEvidence(
        path=field.path,
        observed_types=[entry.type_name for entry in field.observed_types],
        present_ratio=field.present_ratio,
        null_ratio=field.null_ratio,
        unique_ratio=field.unique_ratio,
        candidate_id=field.candidate_id,
        examples=field.sample_values[:3],
        aliases=field.original_names[:3],
        max_array_length=field.max_array_length,
    )


def _pack_sample(sample: SampleRecord) -> PackedSampleEvidence:
    """Convert a representative sample into compact packed evidence."""

    return PackedSampleEvidence(
        index=sample.index,
        record_id=sample.record_id,
        covered_paths=sample.covered_paths,
        record=sample.record,
    )


def _estimate_size(bundle: PackedEvidenceBundle) -> int:
    """Estimate the serialized size of an evidence bundle."""

    return len(json.dumps(bundle.model_dump(mode="json"), sort_keys=True, ensure_ascii=True))


def _ensure_at_least_one_sample(bundle: PackedEvidenceBundle, sample: SampleRecord) -> PackedEvidenceBundle:
    """Try to preserve at least one representative sample within the budget."""

    candidate = bundle.model_copy(deep=True)
    while candidate.fields:
        candidate.fields.pop()
        tentative = candidate.model_copy(deep=True)
        tentative.samples = [_pack_sample(sample)]
        tentative.estimated_size = _estimate_size(tentative)
        if tentative.estimated_size <= candidate.budget:
            return tentative
        candidate = tentative.model_copy(deep=True, update={"samples": []})
    return bundle


def _field_score(field: FieldProfile) -> float:
    """Score a field profile by how valuable it is for packed evidence."""

    score = field.present_ratio + field.unique_ratio
    if field.candidate_id:
        score += 1.0
    if "." in field.path:
        score += 0.3
    if "[]" in field.path:
        score += 0.45
    if field.path.endswith(".id") or field.path.endswith("[].id"):
        score += 0.75
    if 0.0 < field.present_ratio < 0.5:
        score += 0.25
    if field.max_array_length:
        score += 0.2
    score += min(len(field.observed_types), 3) * 0.05
    return score
