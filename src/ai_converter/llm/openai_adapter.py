"""OpenAI-backed adapter implementation for the shared ``LLMAdapter`` contract."""

from __future__ import annotations

import importlib
import json
from typing import Any, Mapping, TypeVar

from pydantic import BaseModel, ValidationError

from .protocol import LLMAdapter, LLMError, LLMResponse, LLMUsage, PromptEnvelope

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class OpenAILLMAdapter(LLMAdapter):
    """Concrete ``LLMAdapter`` backed by the OpenAI Python SDK."""

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the OpenAI-backed adapter.

        Args:
            model: Default OpenAI model name for generated responses.
            client: Optional injected OpenAI-compatible client for tests.
            api_key: Optional API key forwarded into ``openai.OpenAI``.
            base_url: Optional base URL for compatible OpenAI endpoints.
            organization: Optional OpenAI organization identifier.
            project: Optional OpenAI project identifier.
            timeout: Optional client timeout in seconds.

        Returns:
            None.
        """

        self._model = model
        self._client = client
        self._client_kwargs = {
            key: value
            for key, value in {
                "api_key": api_key,
                "base_url": base_url,
                "organization": organization,
                "project": project,
                "timeout": timeout,
            }.items()
            if value is not None
        }

    def generate_text(
        self,
        prompt: PromptEnvelope,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[str]:
        """Generate raw text using the OpenAI Responses API.

        Args:
            prompt: Rendered prompt envelope to send to the OpenAI client.
            metadata: Optional deterministic request metadata.

        Returns:
            Unified response containing the raw text output and adapter metadata.
        """

        combined_metadata = self._combined_metadata(prompt, metadata)
        try:
            response = self._client_instance().responses.create(
                model=self._model,
                input=self._input_items(prompt),
                metadata=self._request_metadata(combined_metadata) or None,
            )
            raw_text = self._response_text(response)
            return LLMResponse(
                raw_text=raw_text,
                parsed=raw_text,
                usage=self._usage(response),
                metadata=combined_metadata,
                prompt=prompt,
            )
        except Exception as error:  # pragma: no cover - exercised via adapter tests
            return self._error_response(prompt, combined_metadata, error)

    def generate_structured(
        self,
        prompt: PromptEnvelope,
        *,
        schema: type[StructuredModelT],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse[StructuredModelT]:
        """Generate structured output using the OpenAI parse helper.

        Args:
            prompt: Rendered prompt envelope to send to the OpenAI client.
            schema: Pydantic schema used for structured parsing.
            metadata: Optional deterministic request metadata.

        Returns:
            Unified response containing raw text, parsed output, and metadata.
        """

        combined_metadata = self._combined_metadata(prompt, metadata)
        try:
            response = self._client_instance().responses.parse(
                model=self._model,
                input=self._input_items(prompt),
                text_format=schema,
                metadata=self._request_metadata(combined_metadata) or None,
            )
            raw_text = self._response_text(response)
            parsed = self._parsed_output(response, schema=schema, raw_text=raw_text)
            return LLMResponse(
                raw_text=raw_text,
                parsed=parsed,
                usage=self._usage(response),
                metadata=combined_metadata,
                prompt=prompt,
            )
        except Exception as error:  # pragma: no cover - exercised via adapter tests
            return self._error_response(prompt, combined_metadata, error)

    def _client_instance(self) -> Any:
        """Return the injected or lazily created OpenAI client.

        Returns:
            OpenAI-compatible client with a ``responses`` interface.

        Raises:
            RuntimeError: If the OpenAI SDK is unavailable locally.
        """

        if self._client is None:
            try:
                openai_module = importlib.import_module("openai")
            except ModuleNotFoundError as error:
                raise RuntimeError(
                    "openai package is required for OpenAILLMAdapter; install it before using this adapter"
                ) from error
            self._client = openai_module.OpenAI(**self._client_kwargs)
        return self._client

    def _input_items(self, prompt: PromptEnvelope) -> list[dict[str, str]]:
        """Convert a prompt envelope into Responses API input items.

        Args:
            prompt: Rendered prompt envelope to convert.

        Returns:
            List of system and user input items for the Responses API.
        """

        return [
            {"role": "system", "content": prompt.system_prompt},
            {"role": "user", "content": prompt.user_prompt},
        ]

    def _combined_metadata(
        self,
        prompt: PromptEnvelope,
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Merge prompt metadata with per-call metadata.

        Args:
            prompt: Prompt envelope containing default metadata.
            metadata: Optional per-call metadata.

        Returns:
            Deterministic merged metadata dictionary.
        """

        return {**prompt.metadata, **dict(metadata or {})}

    def _request_metadata(self, metadata: Mapping[str, Any]) -> dict[str, str]:
        """Coerce metadata into the string-valued shape accepted by the SDK.

        Args:
            metadata: Internal metadata dictionary.

        Returns:
            String-keyed, string-valued metadata for SDK requests.
        """

        request_metadata: dict[str, str] = {}
        for key, value in metadata.items():
            request_metadata[str(key)] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        return request_metadata

    def _usage(self, response: Any) -> LLMUsage:
        """Extract usage information from an OpenAI response object.

        Args:
            response: OpenAI response or parse result object.

        Returns:
            Normalized usage metadata for the shared adapter contract.
        """

        usage = getattr(response, "usage", None)
        return LLMUsage(
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    def _response_text(self, response: Any) -> str:
        """Extract raw text from an OpenAI response object.

        Args:
            response: OpenAI response or parse result object.

        Returns:
            Best-effort raw text extracted from the response.
        """

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        output = getattr(response, "output", None) or []
        chunks: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content", [])
            for block in content or []:
                block_type = getattr(block, "type", None)
                if block_type is None and isinstance(block, dict):
                    block_type = block.get("type")
                if block_type in {"output_text", "text"}:
                    text_value = getattr(block, "text", None)
                    if text_value is None and isinstance(block, dict):
                        text_value = block.get("text")
                    if isinstance(text_value, str):
                        chunks.append(text_value)
        return "\n".join(chunk for chunk in chunks if chunk)

    def _parsed_output(
        self,
        response: Any,
        *,
        schema: type[StructuredModelT],
        raw_text: str,
    ) -> StructuredModelT:
        """Extract and validate the parsed structured output from a response.

        Args:
            response: OpenAI parse result object.
            schema: Target Pydantic schema for validation.
            raw_text: Extracted raw text used as a fallback parse source.

        Returns:
            Parsed structured output validated against ``schema``.

        Raises:
            ValidationError: If the parsed output does not match ``schema``.
        """

        output_parsed = getattr(response, "output_parsed", None)
        if isinstance(output_parsed, schema):
            return output_parsed
        if output_parsed is not None:
            return schema.model_validate(output_parsed)
        if raw_text:
            try:
                return schema.model_validate_json(raw_text)
            except ValidationError:
                return schema.model_validate(json.loads(raw_text))
        raise ValidationError.from_exception_data(schema.__name__, [])

    def _error_response(
        self,
        prompt: PromptEnvelope,
        metadata: dict[str, Any],
        error: Exception,
    ) -> LLMResponse[Any]:
        """Convert one adapter exception into a structured error response.

        Args:
            prompt: Prompt envelope associated with the failed request.
            metadata: Request metadata associated with the failed request.
            error: Exception raised while calling the SDK.

        Returns:
            Unified error response for the shared adapter contract.
        """

        return LLMResponse(
            raw_text="",
            parsed=None,
            metadata=metadata,
            errors=[LLMError(code=error.__class__.__name__, message=str(error), retryable=False)],
            prompt=prompt,
        )
