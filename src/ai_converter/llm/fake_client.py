"""Deterministic fake LLM adapter used by offline unit tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from .protocol import LLMAdapter, LLMError, LLMResponse, LLMUsage, PromptEnvelope

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


@dataclass(slots=True)
class FakeLLMReply:
    """Queued fake response consumed by ``FakeLLMAdapter``.

    Attributes:
        raw_text: Raw response text that the adapter should return.
        parsed_payload: Optional parsed payload used for structured requests.
        metadata: Extra response metadata merged into the returned response.
        usage: Optional token-accounting information for the fake response.
        errors: Optional prebuilt structured errors for the fake response.
    """

    raw_text: str = ""
    parsed_payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: LLMUsage = field(default_factory=LLMUsage)
    errors: list[LLMError] = field(default_factory=list)


@dataclass(slots=True)
class FakeLLMCall:
    """Recorded fake-adapter invocation for later assertions.

    Attributes:
        method: Name of the adapter method that was called.
        prompt: Rendered prompt envelope passed into the adapter.
        metadata: Request metadata supplied by the caller.
        schema_name: Structured schema name for structured calls.
    """

    method: str
    prompt: PromptEnvelope
    metadata: dict[str, Any]
    schema_name: str | None = None


class FakeLLMAdapter(LLMAdapter):
    """Deterministic adapter that pops queued replies instead of calling a model."""

    def __init__(
        self,
        *,
        text_replies: Sequence[FakeLLMReply] | None = None,
        structured_replies: Sequence[FakeLLMReply] | None = None,
    ) -> None:
        """Initialize the fake adapter with optional queued replies.

        Args:
            text_replies: Initial queue for ``generate_text`` calls.
            structured_replies: Initial queue for ``generate_structured`` calls.

        Returns:
            None.
        """

        self._text_replies = list(text_replies or [])
        self._structured_replies = list(structured_replies or [])
        self.calls: list[FakeLLMCall] = []

    def enqueue_text_reply(self, reply: FakeLLMReply) -> None:
        """Append one reply to the text-generation queue.

        Args:
            reply: Fake reply to consume on the next text-generation call.

        Returns:
            None.
        """

        self._text_replies.append(reply)

    def enqueue_structured_reply(self, reply: FakeLLMReply) -> None:
        """Append one reply to the structured-generation queue.

        Args:
            reply: Fake reply to consume on the next structured-generation call.

        Returns:
            None.
        """

        self._structured_replies.append(reply)

    def generate_text(
        self,
        prompt: PromptEnvelope,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[str]:
        """Return the next queued text reply.

        Args:
            prompt: Rendered prompt envelope for the fake request.
            metadata: Optional deterministic request metadata.

        Returns:
            A unified ``LLMResponse`` containing the queued raw text.
        """

        request_metadata = dict(metadata or {})
        reply = self._pop_reply(self._text_replies, method="generate_text")
        self.calls.append(FakeLLMCall("generate_text", prompt, request_metadata))
        return LLMResponse(
            raw_text=reply.raw_text,
            parsed=reply.raw_text,
            usage=reply.usage,
            metadata={**reply.metadata, **request_metadata},
            errors=list(reply.errors),
            prompt=prompt,
        )

    def generate_structured(
        self,
        prompt: PromptEnvelope,
        *,
        schema: type[StructuredModelT],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[StructuredModelT]:
        """Return the next queued structured reply validated against ``schema``.

        Args:
            prompt: Rendered prompt envelope for the fake request.
            schema: Pydantic model used to validate the queued payload.
            metadata: Optional deterministic request metadata.

        Returns:
            A unified ``LLMResponse`` with the validated structured payload.
        """

        request_metadata = dict(metadata or {})
        reply = self._pop_reply(self._structured_replies, method="generate_structured")
        self.calls.append(FakeLLMCall("generate_structured", prompt, request_metadata, schema.__name__))

        parsed, parse_errors = self._coerce_structured_payload(reply, schema)
        return LLMResponse(
            raw_text=self._resolve_raw_text(reply),
            parsed=parsed,
            usage=reply.usage,
            metadata={**reply.metadata, **request_metadata},
            errors=[*reply.errors, *parse_errors],
            prompt=prompt,
        )

    def _pop_reply(self, queue: list[FakeLLMReply], *, method: str) -> FakeLLMReply:
        """Pop one fake reply or synthesize a deterministic error reply.

        Args:
            queue: Reply queue associated with the target adapter method.
            method: Adapter method name used for diagnostics.

        Returns:
            The next queued reply, or a synthetic error reply if the queue is empty.
        """

        if queue:
            return queue.pop(0)
        return FakeLLMReply(
            errors=[
                LLMError(
                    code="missing_fake_reply",
                    message=f"no queued fake reply for {method}",
                    retryable=False,
                )
            ]
        )

    def _coerce_structured_payload(
        self,
        reply: FakeLLMReply,
        schema: type[StructuredModelT],
    ) -> tuple[StructuredModelT | None, list[LLMError]]:
        """Validate one queued structured payload against ``schema``.

        Args:
            reply: Queued fake reply to coerce.
            schema: Pydantic model used for validation.

        Returns:
            A tuple of parsed payload and parsing errors.
        """

        payload = reply.parsed_payload
        if payload is None and reply.raw_text:
            try:
                payload = json.loads(reply.raw_text)
            except json.JSONDecodeError as error:
                return None, [LLMError(code="invalid_json", message=str(error), retryable=False)]

        if payload is None:
            return None, [LLMError(code="missing_payload", message="structured payload is missing", retryable=False)]

        try:
            if isinstance(payload, BaseModel):
                return schema.model_validate(payload.model_dump(mode="json")), []
            return schema.model_validate(payload), []
        except ValidationError as error:
            return None, [LLMError(code="validation_error", message=str(error), retryable=False)]

    def _resolve_raw_text(self, reply: FakeLLMReply) -> str:
        """Return deterministic raw text for one queued reply.

        Args:
            reply: Queued fake reply to stringify when needed.

        Returns:
            Raw response text that mirrors the structured payload when absent.
        """

        if reply.raw_text:
            return reply.raw_text
        payload = reply.parsed_payload
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
