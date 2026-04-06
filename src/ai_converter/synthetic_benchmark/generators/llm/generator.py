"""Orchestration for LLM-assisted synthetic template generation."""

from __future__ import annotations

from pathlib import Path

from ai_converter.llm.protocol import LLMAdapter

from .cache import AcceptedTemplateCache, build_cache_key, build_prompt_hash, template_fingerprint
from .models import (
    AcceptedTemplateCacheEntry,
    SYNTHETIC_TEMPLATE_PROMPT_FAMILY,
    TemplateGenerationAttemptRecord,
    TemplateGenerationCandidate,
    TemplateGenerationRequest,
    TemplateGenerationResult,
)
from .prompt_builder import render_template_generation_prompt
from .validator import TemplateCandidateValidator


class SyntheticTemplateLLMGenerator:
    """Generate structurally diverse but deterministic synthetic templates."""

    def __init__(
        self,
        adapter: LLMAdapter,
        *,
        validator: TemplateCandidateValidator | None = None,
        cache: AcceptedTemplateCache | None = None,
    ) -> None:
        """Initialize the generator with one adapter and helper surfaces.

        Args:
            adapter: Shared LLM adapter used for structured generation.
            validator: Optional validator override for focused tests.
            cache: Optional cache helper override for focused tests.
        """

        self._adapter = adapter
        self._validator = validator or TemplateCandidateValidator()
        self._cache = cache or AcceptedTemplateCache()

    def generate(
        self,
        request: TemplateGenerationRequest,
        *,
        cache_dir: str | Path | None = None,
    ) -> TemplateGenerationResult:
        """Generate one accepted template or a bounded failure result.

        Args:
            request: Generation request that owns inputs and retry knobs.
            cache_dir: Optional accepted-template cache directory.

        Returns:
            Machine-readable generation result.
        """

        accepted_fingerprints = {
            template_fingerprint(template)
            for template in request.accepted_templates
        }
        dry_run_scenario = self._dry_run_scenario(request)
        initial_prompt = render_template_generation_prompt(
            request,
            dry_run_scenario=dry_run_scenario,
            accepted_fingerprints=sorted(accepted_fingerprints),
        )
        prompt_hash = build_prompt_hash(initial_prompt)
        cache_key = build_cache_key(
            prompt_hash=prompt_hash,
            llm_model_config=request.llm_model_config,
            cache_namespace=request.cache_namespace,
        )

        if cache_dir is not None:
            cached = self._cache.load(cache_dir, cache_key)
            if cached is not None:
                return TemplateGenerationResult(
                    status="cache_hit",
                    cache_key=cache_key,
                    prompt_hash=prompt_hash,
                    attempts_used=0,
                    accepted_template=cached.accepted_template,
                    validation_report=cached.validation_report,
                    cache_entry=cached,
                )

        attempts: list[TemplateGenerationAttemptRecord] = []
        prior_failures: list[str] = []
        for attempt_index in range(1, request.max_attempts + 1):
            prompt = render_template_generation_prompt(
                request,
                dry_run_scenario=dry_run_scenario,
                accepted_fingerprints=sorted(accepted_fingerprints),
                prior_failures=prior_failures,
            )
            response = self._adapter.generate_structured(
                prompt,
                schema=TemplateGenerationCandidate,
                metadata={
                    "attempt": attempt_index,
                    "cache_key": cache_key,
                    "dataset_id": request.dataset_id,
                    "prompt_family": SYNTHETIC_TEMPLATE_PROMPT_FAMILY,
                    "llm_model_config": request.llm_model_config,
                },
            )
            if response.parsed is None:
                report = self._validator.build_parse_error_report(response)
            else:
                report = self._validator.validate_candidate(
                    response.parsed,
                    request=request,
                    accepted_fingerprints=accepted_fingerprints,
                )

            attempts.append(
                TemplateGenerationAttemptRecord(
                    attempt=attempt_index,
                    response_trace=response.to_trace_artifact(),
                    validation_report=report,
                )
            )

            if report.valid and report.resolved_template is not None:
                entry = AcceptedTemplateCacheEntry(
                    cache_key=cache_key,
                    prompt_hash=prompt_hash,
                    llm_model_config=request.llm_model_config,
                    accepted_template=report.resolved_template,
                    validation_report=report,
                    response_trace=response.to_trace_artifact(),
                )
                if cache_dir is not None:
                    self._cache.write(cache_dir, entry)
                return TemplateGenerationResult(
                    status="accepted",
                    cache_key=cache_key,
                    prompt_hash=prompt_hash,
                    attempts_used=attempt_index,
                    accepted_template=entry.accepted_template,
                    validation_report=report,
                    attempts=attempts,
                    cache_entry=entry,
                )

            prior_failures.append(self._validator.summarize_failure(report))

        last_report = attempts[-1].validation_report if attempts else None
        return TemplateGenerationResult(
            status="rejected",
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            attempts_used=len(attempts),
            validation_report=last_report,
            attempts=attempts,
            failure_reason=self._validator.summarize_failure(last_report)
            if last_report is not None
            else "template generation failed",
        )

    @staticmethod
    def _dry_run_scenario(request: TemplateGenerationRequest):
        """Materialize the dry-run scenario used for prompt context.

        Args:
            request: Generation request that owns the dry-run knobs.

        Returns:
            Deterministic canonical scenario for prompt context.
        """

        from ai_converter.synthetic_benchmark.generators.deterministic.scenario_sampler import (
            sample_canonical_scenario,
        )

        return sample_canonical_scenario(
            request.dry_run_seed,
            request.dry_run_sampler_config,
        ).scenario
