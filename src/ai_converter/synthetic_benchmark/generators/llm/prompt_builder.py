"""Prompt construction for LLM-assisted synthetic template generation."""

from __future__ import annotations

import json
from typing import Any, Sequence

from pydantic import BaseModel

from ai_converter.llm.prompt_renderers import load_prompt_bundle
from ai_converter.llm.protocol import PromptEnvelope
from ai_converter.synthetic_benchmark.scenario import CanonicalScenario

from .models import (
    SYNTHETIC_TEMPLATE_PROMPT_FAMILY,
    TemplateGenerationCandidate,
    TemplateGenerationRequest,
)


def render_template_generation_prompt(
    request: TemplateGenerationRequest,
    *,
    dry_run_scenario: CanonicalScenario,
    accepted_fingerprints: Sequence[str],
    prior_failures: Sequence[str] | None = None,
) -> PromptEnvelope:
    """Render one file-backed prompt envelope for template generation.

    Args:
        request: Generation request that owns the prompt inputs.
        dry_run_scenario: Canonical scenario used for safe dry-run validation.
        accepted_fingerprints: Structural fingerprints already accepted.
        prior_failures: Optional bounded retry feedback from earlier attempts.

    Returns:
        Rendered prompt envelope for one structured generation call.
    """

    return load_prompt_bundle(
        SYNTHETIC_TEMPLATE_PROMPT_FAMILY,
        version=request.prompt_version,
    ).render(
        "synthetic_template_generation",
        sections={
            "generation_goal": request.generation_goal,
            "base_template_json": _json_text(request.base_template),
            "dry_run_scenario_json": _json_text(dry_run_scenario),
            "output_schema_json": _json_text(TemplateGenerationCandidate.model_json_schema()),
            "accepted_fingerprints_json": _json_text(list(accepted_fingerprints)),
            "guidance_notes": _bullet_block(request.guidance_notes),
            "allow_patches": "yes" if request.allow_patches else "no",
            "prior_failures": _bullet_block(prior_failures or []),
        },
        metadata={
            "family": SYNTHETIC_TEMPLATE_PROMPT_FAMILY,
            "dataset_id": request.dataset_id,
            "allow_patches": request.allow_patches,
            "prompt_version": request.prompt_version,
            "llm_model_config": request.llm_model_config,
        },
    )


def _json_text(value: Any) -> str:
    """Serialize one value into stable pretty JSON for prompt sections.

    Args:
        value: Arbitrary JSON-compatible or Pydantic value.

    Returns:
        Pretty-printed stable JSON text.
    """

    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _bullet_block(lines: Sequence[str]) -> str:
    """Render one deterministic bullet block for prompt sections.

    Args:
        lines: Input bullet contents.

    Returns:
        Multi-line bullet block.
    """

    if not lines:
        return "- none"
    return "\n".join(f"- {line}" for line in lines)
