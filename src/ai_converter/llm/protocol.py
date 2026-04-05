"""Contracts for isolated LLM adapters, prompt envelopes, and call budgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Generic, Literal, Mapping, TypeVar

from pydantic import BaseModel

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
LLMCallBudgetStage = Literal["schema", "mapping", "repair"]


@dataclass(slots=True)
class PromptTemplateReference:
    """Reference to the file-backed prompt template used for one request.

    Attributes:
        family: Logical prompt family such as ``mapping_ir`` or ``repair``.
        version: Version label for the resolved prompt template bundle.
        system_path: Absolute path to the system template file.
        user_path: Absolute path to the user template file.
    """

    family: str
    version: str
    system_path: str
    user_path: str


@dataclass(slots=True)
class PromptEnvelope:
    """Fully rendered prompt pair passed into an ``LLMAdapter``.

    Attributes:
        name: Stable logical name for the rendered prompt.
        version: Prompt version label used during rendering.
        system_prompt: Instruction block for the assistant/system role.
        user_prompt: User-facing payload block with serialized evidence.
        reference: File-backed template reference used to render the prompt.
        metadata: Extra deterministic metadata for downstream tracing.
    """

    name: str
    version: str
    system_prompt: str
    user_prompt: str
    reference: PromptTemplateReference
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMUsage:
    """Token accounting metadata returned by an ``LLMAdapter``.

    Attributes:
        prompt_tokens: Approximate prompt token count when available.
        completion_tokens: Approximate completion token count when available.
        total_tokens: Approximate total token count when available.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        """Return a machine-readable representation of the usage payload.

        Returns:
            Dictionary with prompt, completion, and total token counts.
        """

        return asdict(self)


@dataclass(slots=True)
class LLMError:
    """Structured error emitted by an ``LLMAdapter``.

    Attributes:
        code: Stable machine-readable error code.
        message: Human-readable diagnostic message.
        retryable: Whether the caller may reasonably retry the request.
    """

    code: str
    message: str
    retryable: bool = False


@dataclass(slots=True)
class LLMResponse(Generic[StructuredModelT]):
    """Unified response shape for text and structured generations.

    Attributes:
        raw_text: Raw textual output returned by the adapter.
        parsed: Parsed structured payload when structured generation succeeds.
        usage: Token-accounting information reported by the adapter.
        metadata: Adapter-specific metadata associated with the response.
        errors: Structured errors captured during generation or parsing.
        prompt: Rendered prompt envelope that produced the response.
    """

    raw_text: str
    parsed: StructuredModelT | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[LLMError] = field(default_factory=list)
    prompt: PromptEnvelope | None = None

    @property
    def ok(self) -> bool:
        """Return whether the response completed without structured errors.

        Returns:
            ``True`` when the response contains no errors, otherwise ``False``.
        """

        return not self.errors


@dataclass(slots=True)
class LLMCallBudgetPolicy:
    """Fixed per-stage limits for offline LLM call orchestration.

    Attributes:
        schema: Maximum number of structured calls allowed for schema synthesis.
        mapping: Maximum number of structured calls allowed for mapping synthesis.
        repair: Maximum number of calls reserved for repair synthesis.
    """

    schema: int
    mapping: int
    repair: int

    def __post_init__(self) -> None:
        """Validate that all configured stage limits are non-negative.

        Raises:
            ValueError: If any configured stage limit is negative.
        """

        for stage, value in self.limits().items():
            if value < 0:
                raise ValueError(f"budget for stage {stage!r} must be non-negative")

    def limits(self) -> dict[LLMCallBudgetStage, int]:
        """Return per-stage call limits as a machine-readable mapping.

        Returns:
            Dictionary keyed by budget stage.
        """

        return {
            "schema": self.schema,
            "mapping": self.mapping,
            "repair": self.repair,
        }

    def limit_for(self, stage: LLMCallBudgetStage) -> int:
        """Return the configured limit for one stage.

        Args:
            stage: Budget stage to inspect.

        Returns:
            Configured maximum call count for the stage.
        """

        return self.limits()[stage]

    @property
    def total_limit(self) -> int:
        """Return the total call budget across all supported stages.

        Returns:
            Sum of all configured stage limits.
        """

        return sum(self.limits().values())

    def to_dict(self) -> dict[str, int]:
        """Return a machine-readable representation of the policy.

        Returns:
            Per-stage call limits.
        """

        return self.limits()


@dataclass(slots=True)
class LLMCallBudgetStageUsage:
    """Usage snapshot for one call-budget stage.

    Attributes:
        limit: Maximum number of calls allowed for the stage.
        used: Number of calls already consumed for the stage.
        remaining: Number of calls still available for the stage.
    """

    limit: int
    used: int
    remaining: int

    def to_dict(self) -> dict[str, int]:
        """Return a machine-readable representation of the stage snapshot.

        Returns:
            Dictionary with limit, used, and remaining counters.
        """

        return asdict(self)


@dataclass(slots=True)
class LLMCallRecord:
    """Machine-readable record for one counted adapter call.

    Attributes:
        index: One-based sequence number within the shared ledger.
        stage: Budget stage that consumed the call.
        method: Adapter method name such as ``generate_structured``.
        prompt_name: Logical prompt name used for the call.
        prompt_family: Prompt family used for the call.
        prompt_version: Prompt version label used for the call.
        schema_name: Structured schema name for structured calls, when present.
        metadata: Request metadata forwarded into the adapter.
        usage: Per-call usage payload returned by the adapter.
        ok: Whether the adapter response completed without structured errors.
    """

    index: int
    stage: LLMCallBudgetStage
    method: str
    prompt_name: str
    prompt_family: str
    prompt_version: str
    schema_name: str | None
    metadata: dict[str, Any]
    usage: LLMUsage
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a machine-readable representation of the call record.

        Returns:
            Dictionary describing the counted adapter call.
        """

        payload = asdict(self)
        payload["usage"] = self.usage.to_dict()
        return payload


@dataclass(slots=True)
class LLMCallBudgetSnapshot:
    """Machine-readable snapshot of the shared LLM call budget.

    Attributes:
        policy: Per-stage budget policy used by the ledger.
        stages: Per-stage usage counters.
        total_limit: Total call budget across all stages.
        total_used: Number of calls already consumed.
        total_remaining: Number of calls still available.
        calls: Ordered call records that consumed the budget.
    """

    policy: LLMCallBudgetPolicy
    stages: dict[LLMCallBudgetStage, LLMCallBudgetStageUsage]
    total_limit: int
    total_used: int
    total_remaining: int
    calls: list[LLMCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a machine-readable representation of the full snapshot.

        Returns:
            Dictionary containing policy, stage counters, and call records.
        """

        return {
            "policy": self.policy.to_dict(),
            "stages": {stage: usage.to_dict() for stage, usage in self.stages.items()},
            "total_limit": self.total_limit,
            "total_used": self.total_used,
            "total_remaining": self.total_remaining,
            "calls": [record.to_dict() for record in self.calls],
        }


class LLMCallBudgetExceededError(RuntimeError):
    """Error raised when a shared LLM call budget would be exceeded."""

    def __init__(self, *, stage: LLMCallBudgetStage, snapshot: LLMCallBudgetSnapshot) -> None:
        """Initialize one deterministic budget-exhaustion error.

        Args:
            stage: Stage whose configured budget was exhausted.
            snapshot: Budget snapshot captured before the rejected call.
        """

        self.stage = stage
        self.snapshot = snapshot
        stage_usage = snapshot.stages[stage]
        super().__init__(
            "LLM call budget exhausted for stage "
            f"{stage!r}: used {stage_usage.used} of {stage_usage.limit} allowed calls"
        )


class LLMAdapter(ABC):
    """Abstract contract for offline-testable LLM access layers."""

    @abstractmethod
    def generate_text(
        self,
        prompt: PromptEnvelope,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[str]:
        """Generate raw text from a rendered prompt.

        Args:
            prompt: Fully rendered prompt envelope to send to the adapter.
            metadata: Optional deterministic request metadata for tracing.

        Returns:
            A unified ``LLMResponse`` carrying the raw text result.
        """

    @abstractmethod
    def generate_structured(
        self,
        prompt: PromptEnvelope,
        *,
        schema: type[StructuredModelT],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[StructuredModelT]:
        """Generate a structured object from a rendered prompt.

        Args:
            prompt: Fully rendered prompt envelope to send to the adapter.
            schema: Pydantic model type used to validate the parsed output.
            metadata: Optional deterministic request metadata for tracing.

        Returns:
            A unified ``LLMResponse`` carrying the raw text and parsed object.
        """


class LLMCallBudgetLedger:
    """Centralized call-budget enforcement and accounting for LLM adapters."""

    def __init__(self, policy: LLMCallBudgetPolicy) -> None:
        """Initialize one shared budget ledger.

        Args:
            policy: Per-stage call limits to enforce.
        """

        self._policy = policy
        self._used: dict[LLMCallBudgetStage, int] = {
            stage: 0 for stage in policy.limits()
        }
        self._calls: list[LLMCallRecord] = []

    @property
    def policy(self) -> LLMCallBudgetPolicy:
        """Return the configured budget policy.

        Returns:
            Shared per-stage call limits.
        """

        return self._policy

    def snapshot(self) -> LLMCallBudgetSnapshot:
        """Return the current machine-readable budget snapshot.

        Returns:
            Snapshot containing per-stage counters and ordered call records.
        """

        stages = {
            stage: LLMCallBudgetStageUsage(
                limit=limit,
                used=self._used[stage],
                remaining=max(limit - self._used[stage], 0),
            )
            for stage, limit in self._policy.limits().items()
        }
        total_used = sum(self._used.values())
        total_limit = self._policy.total_limit
        return LLMCallBudgetSnapshot(
            policy=self._policy,
            stages=stages,
            total_limit=total_limit,
            total_used=total_used,
            total_remaining=max(total_limit - total_used, 0),
            calls=list(self._calls),
        )

    def generate_text(
        self,
        adapter: LLMAdapter,
        prompt: PromptEnvelope,
        *,
        stage: LLMCallBudgetStage,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[str]:
        """Generate text while enforcing the shared budget.

        Args:
            adapter: Underlying adapter to delegate to.
            prompt: Fully rendered prompt envelope.
            stage: Budget stage that should consume the call.
            metadata: Optional request metadata for the adapter.

        Returns:
            Adapter response recorded against the shared budget.
        """

        self._ensure_call_allowed(stage)
        response = adapter.generate_text(prompt, metadata=metadata)
        return self._record_response(
            response,
            stage=stage,
            method="generate_text",
            prompt=prompt,
            schema_name=None,
            metadata=metadata,
        )

    def generate_structured(
        self,
        adapter: LLMAdapter,
        prompt: PromptEnvelope,
        *,
        schema: type[StructuredModelT],
        stage: LLMCallBudgetStage,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[StructuredModelT]:
        """Generate structured output while enforcing the shared budget.

        Args:
            adapter: Underlying adapter to delegate to.
            prompt: Fully rendered prompt envelope.
            schema: Pydantic schema used for structured validation.
            stage: Budget stage that should consume the call.
            metadata: Optional request metadata for the adapter.

        Returns:
            Adapter response recorded against the shared budget.
        """

        self._ensure_call_allowed(stage)
        response = adapter.generate_structured(prompt, schema=schema, metadata=metadata)
        return self._record_response(
            response,
            stage=stage,
            method="generate_structured",
            prompt=prompt,
            schema_name=schema.__name__,
            metadata=metadata,
        )

    def _ensure_call_allowed(self, stage: LLMCallBudgetStage) -> None:
        """Raise when the next call would exceed the configured stage limit.

        Args:
            stage: Budget stage that wants to consume one call.

        Raises:
            LLMCallBudgetExceededError: If the stage budget is exhausted.
        """

        if self._used[stage] >= self._policy.limit_for(stage):
            raise LLMCallBudgetExceededError(stage=stage, snapshot=self.snapshot())

    def _record_response(
        self,
        response: LLMResponse[StructuredModelT],
        *,
        stage: LLMCallBudgetStage,
        method: str,
        prompt: PromptEnvelope,
        schema_name: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> LLMResponse[StructuredModelT]:
        """Persist one counted call in the shared budget ledger.

        Args:
            response: Adapter response to record.
            stage: Budget stage that consumed the call.
            method: Adapter method name.
            prompt: Prompt envelope used for the call.
            schema_name: Structured schema name when applicable.
            metadata: Adapter metadata forwarded by the caller.

        Returns:
            The original response, unchanged.
        """

        self._used[stage] += 1
        self._calls.append(
            LLMCallRecord(
                index=len(self._calls) + 1,
                stage=stage,
                method=method,
                prompt_name=prompt.name,
                prompt_family=prompt.reference.family,
                prompt_version=prompt.version,
                schema_name=schema_name,
                metadata=dict(metadata or {}),
                usage=response.usage,
                ok=response.ok,
            )
        )
        return response
