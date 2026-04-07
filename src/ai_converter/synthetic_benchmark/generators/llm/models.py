"""Models for LLM-assisted synthetic template generation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_converter.synthetic_benchmark.scenario import ScenarioSamplerConfig
from ai_converter.synthetic_benchmark.templates import (
    L0TemplateSpec,
    ShapeVariantPolicy,
    TaskFieldAliases,
)
from ai_converter.synthetic_benchmark.templates.common import OptionalTaskField

SYNTHETIC_TEMPLATE_GENERATOR_VERSION = "1.0"
SYNTHETIC_TEMPLATE_CACHE_VERSION = "1.0"
# FR-2 keeps one live prompt-bundle source of truth for template generation.
SYNTHETIC_TEMPLATE_PROMPT_FAMILY = "synthetic_benchmark_template"
ValidationGateName = Literal["parse", "policy", "dry_run", "serialization", "diversity"]
GenerationStatus = Literal["accepted", "cache_hit", "rejected"]


class L0TemplatePatch(BaseModel):
    """Replacement-style patch applied on top of one base `L0TemplateSpec`."""

    model_config = ConfigDict(extra="forbid")

    template_id: str | None = None
    root_mode: Literal["object", "list"] | None = None
    records_key: str | None = None
    wrap_task_object: bool | None = None
    task_object_key: str | None = None
    field_aliases: TaskFieldAliases | None = None
    optional_fields: list[OptionalTaskField] | None = None
    extra_fields: dict[str, Any] | None = None
    shape_variant_policy: ShapeVariantPolicy | None = None

    def apply(self, base_template: L0TemplateSpec) -> L0TemplateSpec:
        """Apply this patch onto one base template.

        Args:
            base_template: Base template used as the starting point.

        Returns:
            Patched `L0TemplateSpec`.
        """

        payload = base_template.model_dump(mode="json")
        for field_name in self.model_fields:
            field_value = getattr(self, field_name)
            if field_value is None:
                continue
            if isinstance(field_value, BaseModel):
                payload[field_name] = field_value.model_dump(mode="json")
            else:
                payload[field_name] = field_value
        return L0TemplateSpec.model_validate(payload)


class TemplateGenerationCandidate(BaseModel):
    """Structured LLM output for one synthetic template candidate."""

    model_config = ConfigDict(extra="forbid")

    template: L0TemplateSpec | None = None
    patch: L0TemplatePatch | None = None
    candidate_label: str | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def _validate_candidate_surface(self) -> TemplateGenerationCandidate:
        """Require exactly one candidate surface.

        Returns:
            The validated candidate instance.

        Raises:
            ValueError: If both or neither candidate surfaces are present.
        """

        has_template = self.template is not None
        has_patch = self.patch is not None
        if has_template == has_patch:
            raise ValueError("candidate must provide exactly one of template or patch")
        return self

    def resolve(self, *, base_template: L0TemplateSpec) -> L0TemplateSpec:
        """Materialize this candidate into one full template instance.

        Args:
            base_template: Base template used when the candidate is a patch.

        Returns:
            Full resolved `L0TemplateSpec`.
        """

        if self.template is not None:
            return self.template
        assert self.patch is not None
        return self.patch.apply(base_template)


class TemplateGenerationRequest(BaseModel):
    """Inputs and knobs for one synthetic template-generation run."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = "synthetic-benchmark"
    base_template: L0TemplateSpec = Field(default_factory=L0TemplateSpec)
    generation_goal: str = (
        "Produce one structurally distinct but semantically safe L0 template."
    )
    guidance_notes: list[str] = Field(default_factory=list)
    accepted_templates: list[L0TemplateSpec] = Field(default_factory=list)
    llm_model_config: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str = "v1"
    cache_namespace: str = "default"
    allow_patches: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    dry_run_seed: int = 7
    dry_run_sampler_config: ScenarioSamplerConfig = Field(
        default_factory=lambda: ScenarioSamplerConfig(
            task_count=2,
            include_assignees=True,
            include_tags=True,
        )
    )


class ValidationIssue(BaseModel):
    """One machine-readable issue emitted by a validation gate."""

    model_config = ConfigDict(extra="forbid")

    gate: ValidationGateName
    code: str
    message: str
    location: str | None = None


class ValidationGateResult(BaseModel):
    """Outcome for one named validation gate."""

    model_config = ConfigDict(extra="forbid")

    gate: ValidationGateName
    passed: bool
    detail: str


class TemplateValidationReport(BaseModel):
    """Machine-readable validation result for one candidate template."""

    model_config = ConfigDict(extra="forbid")

    version: str = SYNTHETIC_TEMPLATE_GENERATOR_VERSION
    valid: bool
    normalized_fingerprint: str | None = None
    resolved_template: L0TemplateSpec | None = None
    rendered_payload_preview: dict[str, Any] | list[dict[str, Any]] | None = None
    gates: list[ValidationGateResult] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible validation payload.

        Returns:
            Deterministic validation-report payload.
        """

        return self.model_dump(mode="json")


class AcceptedTemplateCacheEntry(BaseModel):
    """Persisted accepted-template cache entry."""

    model_config = ConfigDict(extra="forbid")

    version: str = SYNTHETIC_TEMPLATE_CACHE_VERSION
    cache_key: str
    prompt_hash: str
    llm_model_config: dict[str, Any] = Field(default_factory=dict)
    accepted_template: L0TemplateSpec
    validation_report: TemplateValidationReport
    response_trace: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible cache-entry payload.

        Returns:
            Deterministic cache-entry payload.
        """

        return self.model_dump(mode="json")


class TemplateGenerationAttemptRecord(BaseModel):
    """Audit record for one template-generation attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    response_trace: dict[str, Any]
    validation_report: TemplateValidationReport


class TemplateGenerationResult(BaseModel):
    """Outcome of one LLM-assisted synthetic template-generation run."""

    model_config = ConfigDict(extra="forbid")

    status: GenerationStatus
    cache_key: str
    prompt_hash: str
    attempts_used: int
    accepted_template: L0TemplateSpec | None = None
    validation_report: TemplateValidationReport | None = None
    attempts: list[TemplateGenerationAttemptRecord] = Field(default_factory=list)
    cache_entry: AcceptedTemplateCacheEntry | None = None
    failure_reason: str | None = None
