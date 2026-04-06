"""Public exports for LLM-assisted synthetic template generation."""

from .cache import (
    AcceptedTemplateCache,
    build_cache_key,
    build_prompt_hash,
    canonical_json_hash,
    template_fingerprint,
)
from .generator import SyntheticTemplateLLMGenerator
from .models import (
    AcceptedTemplateCacheEntry,
    L0TemplatePatch,
    TemplateGenerationAttemptRecord,
    TemplateGenerationCandidate,
    TemplateGenerationRequest,
    TemplateGenerationResult,
    TemplateValidationReport,
    ValidationGateResult,
    ValidationIssue,
)
from .prompt_builder import render_template_generation_prompt
from .validator import TemplateCandidateValidator

__all__ = [
    "AcceptedTemplateCache",
    "AcceptedTemplateCacheEntry",
    "L0TemplatePatch",
    "SyntheticTemplateLLMGenerator",
    "TemplateCandidateValidator",
    "TemplateGenerationAttemptRecord",
    "TemplateGenerationCandidate",
    "TemplateGenerationRequest",
    "TemplateGenerationResult",
    "TemplateValidationReport",
    "ValidationGateResult",
    "ValidationIssue",
    "build_cache_key",
    "build_prompt_hash",
    "canonical_json_hash",
    "render_template_generation_prompt",
    "template_fingerprint",
]
