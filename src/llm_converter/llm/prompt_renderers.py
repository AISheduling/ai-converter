"""File-backed prompt renderers for source schema, mapping, and repair flows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from pydantic import BaseModel

from llm_converter.mapping_ir.models import MappingIR, SUPPORTED_OPERATION_KINDS
from llm_converter.profiling.models import ProfileReport
from llm_converter.schema import SourceSchemaSpec, TargetSchemaCard, pack_profile_evidence

from .protocol import PromptEnvelope, PromptTemplateReference

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"


@dataclass(slots=True)
class PromptTemplateBundle:
    """Loaded prompt template bundle for one logical prompt family.

    Attributes:
        reference: File-backed template reference for the loaded bundle.
        system_template: Raw system template text.
        user_template: Raw user template text.
    """

    reference: PromptTemplateReference
    system_template: str
    user_template: str

    def render(
        self,
        name: str,
        *,
        sections: dict[str, str],
        metadata: dict[str, Any] | None = None,
    ) -> PromptEnvelope:
        """Render both template sides into a prompt envelope.

        Args:
            name: Stable logical name for the rendered prompt.
            sections: String placeholders injected into both templates.
            metadata: Optional deterministic metadata for downstream tracing.

        Returns:
            A fully rendered ``PromptEnvelope``.
        """

        return PromptEnvelope(
            name=name,
            version=self.reference.version,
            system_prompt=Template(self.system_template).safe_substitute(sections).strip(),
            user_prompt=Template(self.user_template).safe_substitute(sections).strip(),
            reference=self.reference,
            metadata=dict(metadata or {}),
        )


def load_prompt_bundle(family: str, *, version: str = "v1") -> PromptTemplateBundle:
    """Load one file-backed prompt template bundle from ``prompts/``.

    Args:
        family: Prompt family directory under ``prompts/``.
        version: Template version label to load.

    Returns:
        The loaded ``PromptTemplateBundle``.
    """

    family_dir = PROMPTS_ROOT / family
    system_path = family_dir / f"{version}-system.txt"
    user_path = family_dir / f"{version}-user.txt"
    return PromptTemplateBundle(
        reference=PromptTemplateReference(
            family=family,
            version=version,
            system_path=str(system_path),
            user_path=str(user_path),
        ),
        system_template=system_path.read_text(encoding="utf-8"),
        user_template=user_path.read_text(encoding="utf-8"),
    )


def render_source_schema_prompt(
    report: ProfileReport,
    *,
    budget: int = 1800,
    mode: str = "balanced",
    format_hint: str | None = None,
    version: str = "v1",
) -> PromptEnvelope:
    """Render the source-schema synthesis prompt from a profile report.

    Args:
        report: Deterministic profile report produced by the profiling layer.
        budget: Evidence-packing budget forwarded into the renderer.
        mode: Evidence-packing mode forwarded into the renderer.
        format_hint: Optional format hint included in the packed evidence.
        version: Prompt template version to load.

    Returns:
        A file-backed prompt envelope for source-schema synthesis.
    """

    packed = pack_profile_evidence(report, budget=budget, mode=mode, format_hint=format_hint)
    return load_prompt_bundle("source_schema", version=version).render(
        "source_schema_synthesis",
        sections={
            "evidence_json": _json_text(packed),
            "output_schema_json": _json_text(SourceSchemaSpec.model_json_schema()),
            "format_hint": format_hint or "unspecified",
        },
        metadata={"budget": budget, "mode": mode, "format_hint": format_hint},
    )


def render_mapping_ir_prompt(
    source_schema: SourceSchemaSpec,
    target_schema: TargetSchemaCard,
    *,
    conversion_hint: str | None = None,
    version: str = "v1",
) -> PromptEnvelope:
    """Render the mapping-synthesis prompt from source and target contracts.

    Args:
        source_schema: Canonical source schema available to the synthesizer.
        target_schema: Canonical target schema card for the fixed L1 contract.
        conversion_hint: Optional extra mapping hint for later real adapters.
        version: Prompt template version to load.

    Returns:
        A file-backed prompt envelope for mapping synthesis.
    """

    return load_prompt_bundle("mapping_ir", version=version).render(
        "mapping_ir_synthesis",
        sections={
            "source_schema_json": _json_text(source_schema),
            "target_schema_json": _json_text(target_schema),
            "output_schema_json": _json_text(MappingIR.model_json_schema()),
            "allowed_operations_json": _json_text(list(SUPPORTED_OPERATION_KINDS)),
            "conversion_hint": conversion_hint or "unspecified",
        },
        metadata={"conversion_hint": conversion_hint},
    )


def render_repair_prompt(
    mapping_ir: MappingIR,
    *,
    failing_fixture: dict[str, Any],
    expected: Any,
    actual: Any,
    error_log: str,
    problematic_rules: list[str] | None = None,
    version: str = "v1",
) -> PromptEnvelope:
    """Render the bounded-repair prompt for a failing mapping candidate.

    Args:
        mapping_ir: Current mapping candidate that needs a local repair.
        failing_fixture: Input fixture that reproduced the failure.
        expected: Expected target-side value or object.
        actual: Actual target-side value or object.
        error_log: Execution or validation error log for the failure.
        problematic_rules: Optional rule identifiers that appear responsible.
        version: Prompt template version to load.

    Returns:
        A file-backed prompt envelope for bounded repair.
    """

    return load_prompt_bundle("repair", version=version).render(
        "mapping_ir_repair",
        sections={
            "mapping_ir_json": _json_text(mapping_ir),
            "failing_fixture_json": _json_text(failing_fixture),
            "expected_json": _json_text(expected),
            "actual_json": _json_text(actual),
            "error_log": error_log.strip(),
            "diff_text": _diff_text(expected, actual),
            "problematic_rules": "\n".join(f"- {rule}" for rule in (problematic_rules or [])) or "- none provided",
        },
        metadata={"problematic_rule_count": len(problematic_rules or [])},
    )


def _json_text(value: Any) -> str:
    """Serialize a value into stable JSON text for prompt sections.

    Args:
        value: Arbitrary Python or Pydantic value to serialize.

    Returns:
        Stable pretty-printed JSON text.
    """

    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _diff_text(expected: Any, actual: Any) -> str:
    """Build a compact deterministic diff block for repair prompts.

    Args:
        expected: Expected value or object.
        actual: Actual value or object.

    Returns:
        A textual side-by-side diff surrogate suitable for prompt input.
    """

    expected_text = _json_text(expected).splitlines()
    actual_text = _json_text(actual).splitlines()
    lines = ["EXPECTED vs ACTUAL:"]
    max_len = max(len(expected_text), len(actual_text))
    for index in range(max_len):
        expected_line = expected_text[index] if index < len(expected_text) else ""
        actual_line = actual_text[index] if index < len(actual_text) else ""
        prefix = "  " if expected_line == actual_line else "! "
        lines.append(f"{prefix}EXPECTED: {expected_line}")
        lines.append(f"{prefix}ACTUAL:   {actual_line}")
    return "\n".join(lines)
