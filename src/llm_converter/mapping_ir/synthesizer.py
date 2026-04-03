"""Offline synthesis orchestrators for source schemas and MappingIR candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_converter.llm.prompt_renderers import render_mapping_ir_prompt, render_source_schema_prompt
from llm_converter.llm.protocol import LLMAdapter, LLMResponse
from llm_converter.profiling.models import ProfileReport
from llm_converter.schema import SourceSchemaSpec, TargetSchemaCard

from .models import MappingIR
from .ranker import RankedCandidate, evaluate_candidate
from .validator import MappingIRValidator, ValidationIssue, ValidationResult


@dataclass(slots=True)
class MappingCandidateRecord:
    """One synthesized mapping candidate together with ranking metadata.

    Attributes:
        index: Zero-based candidate index from the synthesis loop.
        response: Raw adapter response for the candidate.
        ranked: Deterministic ranking result derived from validation and coverage.
    """

    index: int
    response: LLMResponse[MappingIR]
    ranked: RankedCandidate


@dataclass(slots=True)
class MappingSynthesisResult:
    """Full result of a multi-candidate MappingIR synthesis pass.

    Attributes:
        candidates: Candidate records evaluated during synthesis.
        best_candidate: Best ranked mapping candidate, or ``None`` if unavailable.
        best_index: Zero-based index of the selected candidate, if any.
    """

    candidates: list[MappingCandidateRecord]
    best_candidate: MappingIR | None
    best_index: int | None


class MappingSynthesizer:
    """Run fake- or real-backed synthesis for source schemas and MappingIR."""

    def __init__(self, adapter: LLMAdapter, *, validator: MappingIRValidator | None = None) -> None:
        """Initialize the synthesizer with an adapter and optional validator.

        Args:
            adapter: Adapter used for structured offline generation.
            validator: Optional validator reused across candidate ranking calls.

        Returns:
            None.
        """

        self._adapter = adapter
        self._validator = validator or MappingIRValidator()

    def synthesize_source_schema(
        self,
        report: ProfileReport,
        *,
        budget: int = 1800,
        mode: str = "balanced",
        format_hint: str | None = None,
        version: str = "v1",
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse[SourceSchemaSpec]:
        """Generate one source-schema candidate from a profile report.

        Args:
            report: Deterministic profile report used as input evidence.
            budget: Evidence budget forwarded into the prompt renderer.
            mode: Evidence packing mode forwarded into the prompt renderer.
            format_hint: Optional format hint included in prompt metadata.
            version: Prompt template version to render.
            metadata: Optional extra request metadata for the adapter.

        Returns:
            Structured adapter response for ``SourceSchemaSpec`` generation.
        """

        prompt = render_source_schema_prompt(
            report,
            budget=budget,
            mode=mode,
            format_hint=format_hint,
            version=version,
        )
        return self._adapter.generate_structured(prompt, schema=SourceSchemaSpec, metadata=metadata)

    def synthesize_mapping(
        self,
        source_schema: SourceSchemaSpec,
        target_schema: TargetSchemaCard,
        *,
        candidate_count: int = 3,
        conversion_hint: str | None = None,
        version: str = "v1",
        metadata: dict[str, Any] | None = None,
    ) -> MappingSynthesisResult:
        """Generate and rank multiple mapping candidates deterministically.

        Args:
            source_schema: Canonical source schema contract.
            target_schema: Canonical target schema card.
            candidate_count: Number of structured mapping candidates to request.
            conversion_hint: Optional extra conversion hint for the prompt.
            version: Prompt template version to render.
            metadata: Optional extra request metadata for the adapter.

        Returns:
            Deterministic synthesis result with ranked candidates and the winner.
        """

        prompt = render_mapping_ir_prompt(
            source_schema,
            target_schema,
            conversion_hint=conversion_hint,
            version=version,
        )

        records: list[MappingCandidateRecord] = []
        for index in range(candidate_count):
            response = self._adapter.generate_structured(
                prompt,
                schema=MappingIR,
                metadata={**dict(metadata or {}), "candidate_index": index},
            )
            validation = self._validation_for_response(
                response,
                source_schema=source_schema,
                target_schema=target_schema,
            )
            ranked = evaluate_candidate(response.parsed, validation=validation, target_schema=target_schema)
            records.append(MappingCandidateRecord(index=index, response=response, ranked=ranked))

        ordered = sorted(records, key=lambda item: (-item.ranked.score, item.ranked.fingerprint))
        best = ordered[0] if ordered else None
        return MappingSynthesisResult(
            candidates=ordered,
            best_candidate=best.ranked.candidate if best is not None else None,
            best_index=best.index if best is not None else None,
        )

    def _validation_for_response(
        self,
        response: LLMResponse[MappingIR],
        *,
        source_schema: SourceSchemaSpec,
        target_schema: TargetSchemaCard,
    ) -> ValidationResult:
        """Build a validation verdict for one adapter response.

        Args:
            response: Structured adapter response to validate.
            source_schema: Canonical source schema contract.
            target_schema: Canonical target schema card.

        Returns:
            Validation result for the response payload.
        """

        if response.parsed is None:
            message = response.errors[0].message if response.errors else "mapping candidate did not parse"
            return ValidationResult(
                valid=False,
                issues=[ValidationIssue(code="parse_error", message=message, location="response")],
            )
        return self._validator.validate(
            response.parsed,
            source_schema=source_schema,
            target_schema=target_schema,
        )
