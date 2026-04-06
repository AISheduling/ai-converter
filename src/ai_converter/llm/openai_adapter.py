"""OpenAI-backed adapter implementation for the shared ``LLMAdapter`` contract."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
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
        """Generate structured output using explicit strict Responses formatting.

        Args:
            prompt: Rendered prompt envelope to send to the OpenAI client.
            schema: Pydantic schema used for structured parsing.
            metadata: Optional deterministic request metadata.

        Returns:
            Unified response containing raw text, parsed output, and metadata.
        """

        combined_metadata = self._combined_metadata(prompt, metadata)
        try:
            response, response_metadata = self._structured_response(
                prompt,
                schema=schema,
                metadata=combined_metadata,
            )
            raw_text = self._response_text(response)
            parsed = self._parsed_output(response, schema=schema, raw_text=raw_text)
            return LLMResponse(
                raw_text=raw_text,
                parsed=parsed,
                usage=self._usage(response),
                metadata=response_metadata,
                prompt=prompt,
            )
        except Exception as error:  # pragma: no cover - exercised via adapter tests
            return self._error_response(prompt, combined_metadata, error)

    def _structured_response(
        self,
        prompt: PromptEnvelope,
        *,
        schema: type[StructuredModelT],
        metadata: Mapping[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Create one structured response, retrying with JSON mode when needed.

        Args:
            prompt: Rendered prompt envelope to send to the OpenAI client.
            schema: Pydantic schema used for structured parsing.
            metadata: Deterministic merged metadata for the request.

        Returns:
            Tuple of raw response object and trace metadata for the chosen mode.
        """

        request_metadata = self._request_metadata(metadata) or None
        try:
            return (
                self._client_instance().responses.create(
                    model=self._model,
                    input=self._input_items(prompt),
                    text={"format": self._text_format(schema)},
                    metadata=request_metadata,
                ),
                {**metadata, "structured_output_mode": "json_schema_strict"},
            )
        except Exception as error:
            if not self._should_retry_with_json_object(error):
                raise
            return (
                self._client_instance().responses.create(
                    model=self._model,
                    input=self._input_items(prompt),
                    text={"format": {"type": "json_object"}},
                    metadata=request_metadata,
                ),
                {
                    **metadata,
                    "structured_output_mode": "json_object_fallback",
                    "structured_output_fallback_reason": str(error),
                },
            )

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

    @staticmethod
    def _input_items(prompt: PromptEnvelope) -> list[dict[str, str]]:
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

    @staticmethod
    def _combined_metadata(
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

    @staticmethod
    def _request_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
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

    @classmethod
    def _text_format(cls, schema: type[StructuredModelT]) -> dict[str, Any]:
        """Build an explicit strict Responses API text-format payload.

        Args:
            schema: Pydantic model type expected from the response.

        Returns:
            Responses API ``text.format`` payload with strict JSON Schema.
        """

        return {
            "type": "json_schema",
            "strict": True,
            "name": schema.__name__,
            "schema": cls._to_strict_json_schema(deepcopy(schema.model_json_schema())),
        }

    @staticmethod
    def _should_retry_with_json_object(error: Exception) -> bool:
        """Return whether one structured-schema error should fall back to JSON mode."""

        message = str(error)
        return "invalid_json_schema" in message or "Invalid schema for response_format" in message

    @classmethod
    def _to_strict_json_schema(
        cls,
        json_schema: object,
        *,
        path: tuple[str, ...] = (),
        root: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        """Normalize one Pydantic JSON Schema into OpenAI strict form.

        Args:
            json_schema: JSON Schema node to normalize.
            path: Debug-only traversal path used in validation errors.
            root: Root schema dictionary for resolving local ``$ref`` pointers.

        Returns:
            Strict JSON Schema node compatible with Responses structured output.
        """

        if not isinstance(json_schema, dict):
            raise TypeError(f"Expected JSON schema dictionary at path {path!r}, got {type(json_schema).__name__}")

        if root is None:
            root = json_schema

        defs = json_schema.get("$defs")
        if isinstance(defs, dict):
            for def_name, def_schema in defs.items():
                cls._to_strict_json_schema(def_schema, path=(*path, "$defs", def_name), root=root)

        definitions = json_schema.get("definitions")
        if isinstance(definitions, dict):
            for definition_name, definition_schema in definitions.items():
                cls._to_strict_json_schema(
                    definition_schema,
                    path=(*path, "definitions", definition_name),
                    root=root,
                )

        if json_schema.get("type") == "object" and "additionalProperties" not in json_schema:
            json_schema["additionalProperties"] = False

        properties = json_schema.get("properties")
        if isinstance(properties, dict):
            json_schema["required"] = list(properties.keys())
            json_schema["properties"] = {
                key: cls._to_strict_json_schema(prop_schema, path=(*path, "properties", key), root=root)
                for key, prop_schema in properties.items()
            }

        items = json_schema.get("items")
        if isinstance(items, dict):
            json_schema["items"] = cls._to_strict_json_schema(items, path=(*path, "items"), root=root)

        additional_properties = json_schema.get("additionalProperties")
        if isinstance(additional_properties, dict):
            json_schema["additionalProperties"] = cls._to_strict_json_schema(
                additional_properties,
                path=(*path, "additionalProperties"),
                root=root,
            )

        any_of = json_schema.get("anyOf")
        if isinstance(any_of, list):
            json_schema["anyOf"] = [
                cls._to_strict_json_schema(variant, path=(*path, "anyOf", str(index)), root=root)
                for index, variant in enumerate(any_of)
            ]

        all_of = json_schema.get("allOf")
        if isinstance(all_of, list):
            if len(all_of) == 1:
                json_schema.update(cls._to_strict_json_schema(all_of[0], path=(*path, "allOf", "0"), root=root))
                json_schema.pop("allOf")
            else:
                json_schema["allOf"] = [
                    cls._to_strict_json_schema(entry, path=(*path, "allOf", str(index)), root=root)
                    for index, entry in enumerate(all_of)
                ]

        if json_schema.get("default", object()) is None:
            json_schema.pop("default")

        ref = json_schema.get("$ref")
        if isinstance(ref, str) and cls._has_more_than_n_keys(json_schema, 1):
            resolved = cls._resolve_ref(root=root, ref=ref)
            if not isinstance(resolved, dict):
                raise TypeError(f"Expected resolved $ref {ref!r} to be a dictionary")
            json_schema.update({**resolved, **json_schema})
            json_schema.pop("$ref")
            return cls._to_strict_json_schema(json_schema, path=path, root=root)

        return json_schema

    @staticmethod
    def _resolve_ref(*, root: dict[str, object], ref: str) -> object:
        """Resolve one local JSON Schema reference against the root schema."""

        if not ref.startswith("#/"):
            raise ValueError(f"Unexpected $ref format {ref!r}; expected a local schema reference")

        resolved: object = root
        for key in ref[2:].split("/"):
            if not isinstance(resolved, dict):
                raise TypeError(f"Encountered non-dictionary schema node while resolving {ref!r}")
            resolved = resolved[key]
        return resolved

    @staticmethod
    def _has_more_than_n_keys(obj: dict[str, object], n: int) -> bool:
        """Return whether a mapping has more than ``n`` keys."""

        index = 0
        for _ in obj:
            index += 1
            if index > n:
                return True
        return False

    @staticmethod
    def _usage(response: Any) -> LLMUsage:
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

    @staticmethod
    def _response_text(response: Any) -> str:
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

    @staticmethod
    def _parsed_output(
        response: Any,
        *,
        schema: type[StructuredModelT],
        raw_text: str,
    ) -> StructuredModelT:
        """Extract and validate the structured output from a response.

        Args:
            response: OpenAI response object.
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

    @staticmethod
    def _error_response(
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
