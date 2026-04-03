"""Contracts for isolated LLM adapters and rendered prompt envelopes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, TypeVar

from pydantic import BaseModel

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


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
