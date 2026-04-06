"""Deterministic renderer from canonical scenarios and templates to `L0` JSON."""

from __future__ import annotations

from typing import Any

from ai_converter.synthetic_benchmark.scenario import CanonicalScenario, CanonicalTask
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec


def render_l0_payload(
    scenario: CanonicalScenario,
    template: L0TemplateSpec,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Render one canonical scenario into an `L0` JSON payload.

    Args:
        scenario: Canonical scenario to render.
        template: Template controlling aliases, nesting, and optional fields.

    Returns:
        `L0` payload as a dictionary or list of dictionaries.
    """

    records = [_render_record(task, template) for task in scenario.tasks]
    if template.root_mode == "list":
        return records
    return {template.records_key: records}


def _render_record(task: CanonicalTask, template: L0TemplateSpec) -> dict[str, Any]:
    """Render one task record according to the template rules.

    Args:
        task: Canonical task entity to render.
        template: Template controlling field placement and optional fields.

    Returns:
        Deterministic source-side record payload.
    """

    aliases = template.field_aliases
    task_payload: dict[str, Any] = {
        aliases.entity_id: task.entity_id,
        aliases.name: task.name,
        aliases.status: task.status,
        aliases.duration_days: task.duration_days,
    }
    if "assignee" in template.optional_fields and task.assignee is not None:
        task_payload[aliases.assignee] = task.assignee
    if "tags" in template.optional_fields and task.tags:
        task_payload[aliases.tags] = list(task.tags)

    record: dict[str, Any]
    if template.wrap_task_object:
        record = {template.task_object_key: task_payload}
    else:
        record = dict(task_payload)

    for field_name, field_value in template.extra_fields.items():
        record[field_name] = field_value
    return record
