"""Focused unit tests for shared LLM adapter implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel

from ai_converter.llm import OpenAILLMAdapter, PromptEnvelope, PromptTemplateReference
from ai_converter.mapping_ir import MappingIR


class DemoStructuredPayload(BaseModel):
    """Simple structured payload used by adapter tests."""

    message: str


@dataclass(slots=True)
class _FakeUsage:
    """Fake usage payload returned by the injected OpenAI-like client."""

    input_tokens: int = 11
    output_tokens: int = 7
    total_tokens: int = 18


class _FakeOpenAIResponse:
    """Fake response object returned by the injected OpenAI-like client."""

    def __init__(self, *, output_text: str, output_parsed=None) -> None:
        """Initialize one fake OpenAI response object.

        Args:
            output_text: Raw text returned by the fake response.
            output_parsed: Optional parsed payload returned by the fake response.

        Returns:
            None.
        """

        self.output_text = output_text
        self.output_parsed = output_parsed
        self.usage = _FakeUsage()
        self.output = []


class _FakeResponsesAPI:
    """Fake ``responses`` namespace used by the injected OpenAI-like client."""

    def __init__(self) -> None:
        """Initialize fake response-method call stores.

        Returns:
            None.
        """

        self.create_calls: list[dict] = []
        self.parse_calls: list[dict] = []

    def create(self, **kwargs):
        """Record and answer one fake ``responses.create`` call.

        Args:
            **kwargs: Request payload forwarded by the adapter.

        Returns:
            Fake text response object.
        """

        self.create_calls.append(kwargs)
        if "text" in kwargs:
            return _FakeOpenAIResponse(output_text='{"message": "structured response"}')
        return _FakeOpenAIResponse(output_text="plain text response")

    def parse(self, **kwargs):
        """Record and answer one fake ``responses.parse`` call.

        Args:
            **kwargs: Request payload forwarded by the adapter.

        Returns:
            Fake structured response object.
        """

        self.parse_calls.append(kwargs)
        return _FakeOpenAIResponse(
            output_text='{"message": "structured response"}',
            output_parsed=DemoStructuredPayload(message="structured response"),
        )


class _FakeOpenAIClient:
    """Fake OpenAI-like client injected into ``OpenAILLMAdapter`` tests."""

    def __init__(self) -> None:
        """Initialize the fake client with a ``responses`` namespace.

        Returns:
            None.
        """

        self.responses = _FakeResponsesAPI()


class _SchemaRejectingResponsesAPI(_FakeResponsesAPI):
    """Fake responses API that rejects strict JSON Schema once, then accepts JSON mode."""

    def create(self, **kwargs):
        """Reject strict JSON Schema formatting and accept the JSON fallback."""

        self.create_calls.append(kwargs)
        format_payload = kwargs.get("text", {}).get("format", {})
        if format_payload.get("type") == "json_schema":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': "
                "\"Invalid schema for response_format 'MappingIR': In context=(), "
                "'required' is required to be supplied and to be an array including every key in properties. "
                "Extra required key 'child_keys' supplied.\", 'code': 'invalid_json_schema'}}"
            )
        return _FakeOpenAIResponse(output_text='{"message": "structured response"}')


class _SchemaRejectingOpenAIClient:
    """Fake client that forces the adapter's JSON-mode compatibility fallback."""

    def __init__(self) -> None:
        self.responses = _SchemaRejectingResponsesAPI()


class _MappingIRCompatibleResponsesAPI(_FakeResponsesAPI):
    """Fake responses API that returns a minimal valid ``MappingIR`` payload."""

    def create(self, **kwargs):
        """Record one call and return a valid ``MappingIR`` JSON payload."""

        self.create_calls.append(kwargs)
        return _FakeOpenAIResponse(
            output_text=(
                '{"version":"1.0","source_refs":[],"steps":[],'
                '"assignments":[],"preconditions":[],"postconditions":[]}'
            )
        )


class _MappingIRCompatibleOpenAIClient:
    """Fake client used to inspect the chosen structured-output mode for ``MappingIR``."""

    def __init__(self) -> None:
        self.responses = _MappingIRCompatibleResponsesAPI()


def test_openai_adapter_generate_text_uses_responses_create() -> None:
    """Verify that ``OpenAILLMAdapter`` uses ``responses.create`` for text.

    Returns:
        None.
    """

    client = _FakeOpenAIClient()
    adapter = OpenAILLMAdapter(client=client, model="gpt-5.4-mini")

    response = adapter.generate_text(_prompt(), metadata={"attempt": 1})

    assert response.ok is True
    assert response.raw_text == "plain text response"
    assert client.responses.create_calls[0]["model"] == "gpt-5.4-mini"
    assert client.responses.create_calls[0]["input"][0]["role"] == "system"
    assert client.responses.create_calls[0]["metadata"] == {
        "family": "mapping_ir",
        "attempt": "1",
    }
    assert response.usage.total_tokens == 18
    assert response.to_dict()["usage"]["total_tokens"] == 18
    assert response.to_dict()["prompt"]["reference"]["family"] == "mapping_ir"
    artifact = response.to_trace_artifact()
    assert artifact["artifact_kind"] == "llm_response_trace"
    assert artifact["artifact_version"] == "1.0"
    assert artifact["raw_text"] == "plain text response"
    assert artifact["parsed"] == "plain text response"
    assert artifact["usage"]["total_tokens"] == 18
    assert artifact["prompt"]["reference"]["family"] == "mapping_ir"
    assert json.loads(json.dumps(artifact)) == artifact


def test_openai_adapter_generate_structured_uses_strict_responses_create() -> None:
    """Verify that ``OpenAILLMAdapter`` sends strict ``text.format`` JSON schema.

    Returns:
        None.
    """

    client = _FakeOpenAIClient()
    adapter = OpenAILLMAdapter(client=client, model="gpt-5.4-mini")

    response = adapter.generate_structured(_prompt(), schema=DemoStructuredPayload, metadata={"scenario": "structured"})

    assert response.ok is True
    assert response.parsed == DemoStructuredPayload(message="structured response")
    assert client.responses.create_calls[0]["model"] == "gpt-5.4-mini"
    assert client.responses.create_calls[0]["metadata"] == {
        "family": "mapping_ir",
        "scenario": "structured",
    }
    text_format = client.responses.create_calls[0]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["name"] == "DemoStructuredPayload"
    assert text_format["schema"]["type"] == "object"
    assert text_format["schema"]["additionalProperties"] is False
    assert text_format["schema"]["required"] == ["message"]
    assert text_format["schema"]["properties"]["message"] == {
        "title": "Message",
        "type": "string",
    }
    assert client.responses.parse_calls == []
    assert response.to_dict()["parsed"] == {"message": "structured response"}
    artifact = response.to_trace_artifact()
    assert artifact["artifact_kind"] == "llm_response_trace"
    assert artifact["parsed"] == {"message": "structured response"}
    assert artifact["prompt"]["reference"]["family"] == "mapping_ir"
    assert json.loads(json.dumps(artifact)) == artifact


def test_openai_adapter_strict_text_format_requires_all_mapping_ir_properties() -> None:
    """Verify that the adapter emits OpenAI-strict required arrays for MappingIR."""

    text_format = OpenAILLMAdapter._text_format(MappingIR)
    schema = text_format["schema"]
    step_schema = schema["$defs"]["StepOperation"]

    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["name"] == "MappingIR"
    assert schema["required"] == list(schema["properties"].keys())
    assert step_schema["required"] == list(step_schema["properties"].keys())
    assert step_schema["properties"]["value"] == {"$ref": "#/$defs/JsonValue"}


def test_openai_adapter_falls_back_to_json_object_when_provider_rejects_json_schema() -> None:
    """Verify that strict-schema provider incompatibility falls back to JSON mode."""

    client = _SchemaRejectingOpenAIClient()
    adapter = OpenAILLMAdapter(client=client, model="gpt-5.4-mini")

    response = adapter.generate_structured(_prompt(), schema=DemoStructuredPayload, metadata={"scenario": "structured"})

    assert response.ok is True
    assert response.parsed == DemoStructuredPayload(message="structured response")
    assert [call["text"]["format"]["type"] for call in client.responses.create_calls] == ["json_schema", "json_object"]
    assert response.metadata["structured_output_mode"] == "json_object_fallback"
    assert "invalid_json_schema" in response.metadata["structured_output_fallback_reason"]


def test_openai_adapter_uses_json_object_upfront_for_mapping_ir_proxy_compatibility() -> None:
    """Verify that ``MappingIR`` skips the known-incompatible strict schema mode."""

    client = _MappingIRCompatibleOpenAIClient()
    adapter = OpenAILLMAdapter(client=client, model="gpt-5.4-mini")

    response = adapter.generate_structured(_prompt(), schema=MappingIR, metadata={"scenario": "mapping_ir"})

    assert response.ok is True
    assert response.parsed == MappingIR(
        version="1.0",
        source_refs=[],
        steps=[],
        assignments=[],
        preconditions=[],
        postconditions=[],
    )
    assert [call["text"]["format"]["type"] for call in client.responses.create_calls] == ["json_object"]
    assert response.metadata["structured_output_mode"] == "json_object_proactive"
    assert "proxy_compatibility" in response.metadata["structured_output_fallback_reason"]


def _prompt() -> PromptEnvelope:
    """Build a deterministic prompt envelope used by adapter tests.

    Returns:
        Prompt envelope for focused LLM adapter tests.
    """

    return PromptEnvelope(
        name="mapping_ir_synthesis",
        version="v1",
        system_prompt="System instructions",
        user_prompt="User payload",
        reference=PromptTemplateReference("mapping_ir", "v1", "system.txt", "user.txt"),
        metadata={"family": "mapping_ir"},
    )
