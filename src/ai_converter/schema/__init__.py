"""Schema contract utilities bridging profiling outputs and L1 models."""

from .evidence_packer import (
    EvidenceBudgetExceededError,
    EvidencePackMode,
    PackedEvidenceBundle,
    pack_profile_evidence,
)
from .source_spec_aggregator import merge_source_schema_candidates
from .source_spec_models import SourceFieldSpec, SourceSchemaSpec
from .source_spec_normalizer import normalize_source_schema_spec
from .target_card_builder import build_target_schema_card
from .target_card_models import TargetFieldCard, TargetSchemaCard

__all__ = [
    "EvidenceBudgetExceededError",
    "EvidencePackMode",
    "PackedEvidenceBundle",
    "SourceFieldSpec",
    "SourceSchemaSpec",
    "TargetFieldCard",
    "TargetSchemaCard",
    "build_target_schema_card",
    "merge_source_schema_candidates",
    "normalize_source_schema_spec",
    "pack_profile_evidence",
]
