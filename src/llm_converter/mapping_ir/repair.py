"""Repair-context helpers for bounded MappingIR patch prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_converter.llm.protocol import PromptEnvelope

from .models import MappingIR


@dataclass(slots=True)
class RepairCase:
    """Failure context used to render bounded repair prompts.

    Attributes:
        failing_fixture: Input fixture that reproduced the failure.
        expected: Expected target-side value or object.
        actual: Actual target-side value or object.
        error_log: Execution or validation diagnostics for the failure.
        problematic_rules: Optional list of rules suspected to be responsible.
    """

    failing_fixture: dict[str, Any]
    expected: Any
    actual: Any
    error_log: str
    problematic_rules: list[str] = field(default_factory=list)


def build_repair_prompt(
    mapping_ir: MappingIR,
    repair_case: RepairCase,
    *,
    version: str = "v1",
) -> PromptEnvelope:
    """Render a bounded repair prompt from a failing mapping case.

    Args:
        mapping_ir: Current mapping program that needs a local repair.
        repair_case: Failure context used to build the prompt payload.
        version: Prompt template version to render.

    Returns:
        A rendered prompt envelope for bounded repair.
    """

    from llm_converter.llm.prompt_renderers import render_repair_prompt

    return render_repair_prompt(
        mapping_ir,
        failing_fixture=repair_case.failing_fixture,
        expected=repair_case.expected,
        actual=repair_case.actual,
        error_log=repair_case.error_log,
        problematic_rules=repair_case.problematic_rules,
        version=version,
    )
