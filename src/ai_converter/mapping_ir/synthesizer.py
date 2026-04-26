"""Offline synthesis orchestrators for source schemas and MappingIR candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai_converter.llm.prompt_renderers import render_mapping_ir_prompt, render_source_schema_prompt
from ai_converter.llm.protocol import (
    LLMAdapter,
    LLMCallBudgetLedger,
    LLMCallBudgetPolicy,
    LLMCallBudgetSnapshot,
    LLMCallBudgetStage,
    LLMResponse,
)
from ai_converter.profiling.models import ProfileReport
from ai_converter.schema import SourceSchemaSpec, TargetSchemaCard

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
        budget_accounting: Shared LLM call-budget snapshot after synthesis.
    """

    candidates: list[MappingCandidateRecord]
    best_candidate: MappingIR | None
    best_index: int | None
    budget_accounting: LLMCallBudgetSnapshot | None = None


class MappingSynthesizer:
    """Run fake- or real-backed synthesis for source schemas and MappingIR."""

    def __init__(
        self,
        adapter: LLMAdapter,
        *,
        validator: MappingIRValidator | None = None,
        budget_policy: LLMCallBudgetPolicy | None = None,
    ) -> None:
        """Initialize the synthesizer with an adapter and optional validator.

        Args:
            adapter: Adapter used for structured offline generation.
            validator: Optional validator reused across candidate ranking calls.
            budget_policy: Optional shared LLM call-budget policy for schema,
                mapping, and repair stages.

        Returns:
            None.
        """

        self._adapter = adapter
        self._validator = validator or MappingIRValidator()
        self._budget_ledger = LLMCallBudgetLedger(budget_policy) if budget_policy is not None else None

    @property
    def budget_accounting(self) -> LLMCallBudgetSnapshot | None:
        """Return the current shared LLM call-budget snapshot.

        Returns:
            Shared budget snapshot when a budget policy is configured,
            otherwise ``None``.
        """

        if self._budget_ledger is None:
            return None
        return self._budget_ledger.snapshot()

    def synthesize_source_schema(
        self,
        report: ProfileReport,
        *,
        budget: int = 1800,
        mode: str = "balanced",
        format_hint: str | None = None,
        required_semantic_paths: Mapping[str, Sequence[str]] | None = None,
        version: str = "v1",
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse[SourceSchemaSpec]:
        """Generate one source-schema candidate from a profile report.

        Args:
            report: Deterministic profile report used as input evidence.
            budget: Evidence budget forwarded into the prompt renderer.
            mode: Evidence packing mode forwarded into the prompt renderer.
            format_hint: Optional format hint included in prompt metadata.
            required_semantic_paths: Optional semantic-to-source-path hints
                preserved outside the budgeted evidence bundle.
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
            required_semantic_paths=required_semantic_paths,
            version=version,
        )
        response = self._generate_structured(
            prompt,
            schema=SourceSchemaSpec,
            stage="schema",
            metadata=metadata,
        )
        snapshot = self.budget_accounting
        if snapshot is not None:
            response.metadata = {
                **response.metadata,
                "llm_call_budget": snapshot.to_dict(),
            }
        return response

    def synthesize_mapping(
        self,
        source_schema: SourceSchemaSpec,
        target_schema: TargetSchemaCard,
        *,
        candidate_count: int = 3,
        conversion_hint: str | None = None,
        required_semantic_paths: Mapping[str, Sequence[str]] | None = None,
        version: str = "v1",
        metadata: dict[str, Any] | None = None,
    ) -> MappingSynthesisResult:
        """Generate and rank multiple mapping candidates deterministically.

        Args:
            source_schema: Canonical source schema contract.
            target_schema: Canonical target schema card.
            candidate_count: Number of structured mapping candidates to request.
            conversion_hint: Optional extra conversion hint for the prompt.
            required_semantic_paths: Optional completed semantic-to-source-path
                mapping shown explicitly in the rendered prompt.
            version: Prompt template version to render.
            metadata: Optional extra request metadata for the adapter.

        Returns:
            Deterministic synthesis result with ranked candidates and the winner.
        """

        prompt = render_mapping_ir_prompt(
            source_schema,
            target_schema,
            conversion_hint=conversion_hint,
            required_semantic_paths=required_semantic_paths,
            version=version,
        )

        records: list[MappingCandidateRecord] = []
        for index in range(candidate_count):
            response = self._generate_structured(
                prompt,
                schema=MappingIR,
                stage="mapping",
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
            budget_accounting=self.budget_accounting,
        )

    def _generate_structured(
        self,
        prompt,
        *,
        schema,
        stage: LLMCallBudgetStage,
        metadata: dict[str, Any] | None,
    ):
        """Generate one structured response with optional shared budget checks.

        Args:
            prompt: Rendered prompt envelope for the request.
            schema: Structured schema used to validate the response.
            stage: Shared budget stage that should consume the call.
            metadata: Optional deterministic request metadata.

        Returns:
            Structured adapter response for the requested schema.
        """

        if self._budget_ledger is None:
            return self._adapter.generate_structured(prompt, schema=schema, metadata=metadata)
        return self._budget_ledger.generate_structured(
            self._adapter,
            prompt,
            schema=schema,
            stage=stage,
            metadata=metadata,
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
