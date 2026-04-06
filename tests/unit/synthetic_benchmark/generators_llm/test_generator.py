"""Focused unit tests for the synthetic benchmark LLM generator."""

from __future__ import annotations

import shutil
from pathlib import Path

from ai_converter.llm import FakeLLMAdapter, FakeLLMReply
from ai_converter.synthetic_benchmark import (
    AcceptedTemplateCache,
    AcceptedTemplateCacheEntry,
    L0TemplateSpec,
    SyntheticTemplateLLMGenerator,
    TemplateGenerationRequest,
    TemplateValidationReport,
    ValidationGateResult,
    build_cache_key,
    build_prompt_hash,
    render_l0_payload,
    render_template_generation_prompt,
    sample_canonical_scenario,
    template_fingerprint,
)

ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "synthetic_benchmark" / "llm_templates"


def test_prompt_builder_renders_deterministic_prompt_sections() -> None:
    """Verify that the prompt builder renders deterministic template inputs."""

    request = TemplateGenerationRequest(
        guidance_notes=["Prefer wrapped records."],
        llm_model_config={"model": "fake-template-model"},
    )
    sampled = sample_canonical_scenario(
        request.dry_run_seed,
        request.dry_run_sampler_config,
    )

    prompt = render_template_generation_prompt(
        request,
        dry_run_scenario=sampled.scenario,
        accepted_fingerprints=["abc123"],
        prior_failures=["policy:duplicate_required_alias"],
    )

    assert prompt.reference.family == "synthetic_benchmark_template"
    assert prompt.reference.version == "v1"
    assert sampled.scenario.scenario_id in prompt.user_prompt
    assert '"template"' in prompt.user_prompt
    assert "abc123" in prompt.user_prompt
    assert "Prefer wrapped records." in prompt.user_prompt
    assert prompt.metadata["family"] == "synthetic_benchmark_template"


def test_llm_template_output_is_parsed_and_validated() -> None:
    """Verify that a structured template candidate is accepted offline."""

    adapter = FakeLLMAdapter(
        structured_replies=[FakeLLMReply(parsed_payload={"template": _valid_template_payload()})]
    )
    generator = SyntheticTemplateLLMGenerator(adapter)

    result = generator.generate(
        TemplateGenerationRequest(
            guidance_notes=["Use a wrapped task object."],
            llm_model_config={"model": "fake-template-model"},
        )
    )

    assert result.status == "accepted"
    assert result.accepted_template is not None
    assert result.validation_report is not None
    assert result.validation_report.valid is True
    assert result.validation_report.normalized_fingerprint
    assert adapter.calls[0].schema_name == "TemplateGenerationCandidate"


def test_invalid_template_is_rejected() -> None:
    """Verify that policy-invalid templates are rejected."""

    adapter = FakeLLMAdapter(
        structured_replies=[FakeLLMReply(parsed_payload={"template": _policy_invalid_template_payload()})]
    )
    generator = SyntheticTemplateLLMGenerator(adapter)

    result = generator.generate(TemplateGenerationRequest(max_attempts=1))

    assert result.status == "rejected"
    assert result.validation_report is not None
    assert any(issue.code == "empty_records_key" for issue in result.validation_report.issues)
    assert result.attempts_used == 1


def test_dry_run_instantiation_rejects_broken_template() -> None:
    """Verify that dry-run semantic loss rejects otherwise parseable templates."""

    adapter = FakeLLMAdapter(
        structured_replies=[FakeLLMReply(parsed_payload={"template": _dry_run_invalid_template_payload()})]
    )
    generator = SyntheticTemplateLLMGenerator(adapter)

    result = generator.generate(TemplateGenerationRequest(max_attempts=1))

    assert result.status == "rejected"
    assert result.validation_report is not None
    assert any(issue.gate == "dry_run" for issue in result.validation_report.issues)


def test_cache_hit_skips_client_call() -> None:
    """Verify that a cache hit avoids making a new adapter call."""

    request = TemplateGenerationRequest(
        guidance_notes=["Prefer wrapped records."],
        llm_model_config={"model": "fake-template-model"},
    )
    sampled = sample_canonical_scenario(
        request.dry_run_seed,
        request.dry_run_sampler_config,
    )
    prompt = render_template_generation_prompt(
        request,
        dry_run_scenario=sampled.scenario,
        accepted_fingerprints=[],
    )
    prompt_hash = build_prompt_hash(prompt)
    cache_key = build_cache_key(
        prompt_hash=prompt_hash,
        llm_model_config=request.llm_model_config,
        cache_namespace=request.cache_namespace,
    )
    cached_template = _load_fixture_template("accepted_template.json")
    validation_report = TemplateValidationReport(
        valid=True,
        normalized_fingerprint=template_fingerprint(cached_template),
        resolved_template=cached_template,
        gates=[
            ValidationGateResult(gate="parse", passed=True, detail="cached"),
            ValidationGateResult(gate="policy", passed=True, detail="cached"),
            ValidationGateResult(gate="dry_run", passed=True, detail="cached"),
            ValidationGateResult(gate="serialization", passed=True, detail="cached"),
            ValidationGateResult(gate="diversity", passed=True, detail="cached"),
        ],
    )
    entry = AcceptedTemplateCacheEntry(
        cache_key=cache_key,
        prompt_hash=prompt_hash,
        llm_model_config=request.llm_model_config,
        accepted_template=cached_template,
        validation_report=validation_report,
        response_trace={"artifact_kind": "llm_response_trace"},
    )
    cache_root = ROOT / ".pytest-local-tmp" / "synthetic-template-cache"
    shutil.rmtree(cache_root, ignore_errors=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        AcceptedTemplateCache().write(cache_root, entry)

        adapter = FakeLLMAdapter()
        result = SyntheticTemplateLLMGenerator(adapter).generate(
            request,
            cache_dir=cache_root,
        )

        assert result.status == "cache_hit"
        assert result.accepted_template == cached_template
        assert adapter.calls == []
    finally:
        shutil.rmtree(cache_root, ignore_errors=True)


def test_bounded_retry_stops_after_k_attempts() -> None:
    """Verify that the generator stops after the configured retry limit."""

    adapter = FakeLLMAdapter(
        structured_replies=[
            FakeLLMReply(parsed_payload={"template": _policy_invalid_template_payload()}),
            FakeLLMReply(parsed_payload={"template": _policy_invalid_template_payload()}),
        ]
    )
    generator = SyntheticTemplateLLMGenerator(adapter)

    result = generator.generate(TemplateGenerationRequest(max_attempts=2))

    assert result.status == "rejected"
    assert result.attempts_used == 2
    assert len(result.attempts) == 2
    assert len(adapter.calls) == 2


def test_accepted_template_can_render_valid_l0() -> None:
    """Verify that an accepted template still renders a valid `L0` payload."""

    adapter = FakeLLMAdapter(
        structured_replies=[FakeLLMReply(parsed_payload={"template": _valid_template_payload()})]
    )
    generator = SyntheticTemplateLLMGenerator(adapter)
    request = TemplateGenerationRequest()

    result = generator.generate(request)

    assert result.accepted_template is not None
    payload = render_l0_payload(
        sample_canonical_scenario(request.dry_run_seed, request.dry_run_sampler_config).scenario,
        result.accepted_template,
    )

    assert isinstance(payload, dict)
    assert "items" in payload
    assert "task" in payload["items"][0]


def _valid_template_payload() -> dict[str, object]:
    """Build one valid template payload used by focused acceptance tests."""

    return {
        "template_id": "llm_wrapped_template",
        "root_mode": "object",
        "records_key": "items",
        "wrap_task_object": True,
        "task_object_key": "task",
        "field_aliases": {
            "entity_id": "task_id",
            "name": "title",
            "status": "state",
            "duration_days": "days",
            "assignee": "owner",
            "tags": "labels",
        },
        "optional_fields": ["assignee", "tags"],
        "extra_fields": {"surface": "llm"},
    }


def _policy_invalid_template_payload() -> dict[str, object]:
    """Build one policy-invalid template payload."""

    return {
        "template_id": "broken_policy",
        "root_mode": "object",
        "records_key": "",
        "wrap_task_object": False,
        "task_object_key": "task",
        "field_aliases": {
            "entity_id": "task_id",
            "name": "task_name",
            "status": "status_text",
            "duration_days": "duration_days",
            "assignee": "owner",
            "tags": "labels",
        },
        "optional_fields": ["assignee"],
        "extra_fields": {},
    }


def _dry_run_invalid_template_payload() -> dict[str, object]:
    """Build one template payload that fails dry-run semantic validation."""

    return {
        "template_id": "broken_dry_run",
        "root_mode": "object",
        "records_key": "records",
        "wrap_task_object": False,
        "task_object_key": "task",
        "field_aliases": {
            "entity_id": "task_id",
            "name": "task_name",
            "status": "status_text",
            "duration_days": "duration_days",
            "assignee": "assignee",
            "tags": "tags",
        },
        "optional_fields": ["assignee"],
        "extra_fields": {"task_id": "OVERRIDE"},
    }


def _load_fixture_template(filename: str) -> L0TemplateSpec:
    """Load one deterministic template fixture from disk.

    Args:
        filename: Fixture filename under the LLM template fixture root.

    Returns:
        Parsed template fixture.
    """

    return L0TemplateSpec.model_validate_json(
        (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
    )
