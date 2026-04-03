"""Focused unit tests for shared LLM adapter implementations."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from llm_converter.llm import OpenAILLMAdapter, PromptEnvelope, PromptTemplateReference


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


def test_openai_adapter_generate_structured_uses_responses_parse() -> None:
    """Verify that ``OpenAILLMAdapter`` uses ``responses.parse`` for JSON output.

    Returns:
        None.
    """

    client = _FakeOpenAIClient()
    adapter = OpenAILLMAdapter(client=client, model="gpt-5.4-mini")

    response = adapter.generate_structured(_prompt(), schema=DemoStructuredPayload, metadata={"scenario": "structured"})

    assert response.ok is True
    assert response.parsed == DemoStructuredPayload(message="structured response")
    assert client.responses.parse_calls[0]["model"] == "gpt-5.4-mini"
    assert client.responses.parse_calls[0]["text_format"] is DemoStructuredPayload
    assert client.responses.parse_calls[0]["metadata"] == {
        "family": "mapping_ir",
        "scenario": "structured",
    }


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
