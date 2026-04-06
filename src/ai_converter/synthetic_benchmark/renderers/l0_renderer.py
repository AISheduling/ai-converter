"""Deterministic renderer from canonical scenarios and templates to `L0` JSON."""

from __future__ import annotations

import copy
from typing import Any

from ai_converter.synthetic_benchmark.scenario import CanonicalScenario, CanonicalTask
from ai_converter.synthetic_benchmark.templates import (
    L0TemplateSpec,
    ShapeVariantSpec,
    TaskFieldAliases,
)
from ai_converter.synthetic_benchmark.templates.shape_variants import select_shape_variant


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

    records = [
        _render_record(
            task,
            scenario=scenario,
            template=template,
            record_index=index,
        )
        for index, task in enumerate(scenario.tasks)
    ]
    if template.root_mode == "list":
        return records
    return {template.records_key: records}


def _render_record(
    task: CanonicalTask,
    *,
    scenario: CanonicalScenario,
    template: L0TemplateSpec,
    record_index: int,
) -> dict[str, Any]:
    """Render one task record according to the template rules.

    Args:
        task: Canonical task entity to render.
        scenario: Scenario that owns the task record.
        template: Template controlling field placement and optional fields.
        record_index: Stable zero-based task index.

    Returns:
        Deterministic source-side record payload.
    """

    variant = select_shape_variant(
        template.shape_variant_policy,
        record_index=record_index,
        stable_key=f"{scenario.scenario_id}:{task.entity_id}:{template.template_id}:{record_index}",
    )
    aliases = _resolved_aliases(template, variant)
    optional_fields = _resolved_optional_fields(template, variant)
    task_payload: dict[str, Any] = {
        aliases.entity_id: task.entity_id,
        aliases.name: task.name,
        aliases.status: task.status,
        aliases.duration_days: task.duration_days,
    }
    if "assignee" in optional_fields and task.assignee is not None:
        task_payload[aliases.assignee] = task.assignee
    if "tags" in optional_fields and task.tags:
        task_payload[aliases.tags] = list(task.tags)

    record: dict[str, Any]
    if _resolved_wrap_task_object(template, variant):
        record = {_resolved_task_object_key(template, variant): task_payload}
    else:
        record = dict(task_payload)

    envelope_key = variant.record_envelope_key if variant is not None else None
    if envelope_key is not None:
        record = {envelope_key: record}

    for field_name, field_value in _resolved_extra_fields(template, variant).items():
        record[field_name] = field_value
    return record


def _resolved_aliases(
    template: L0TemplateSpec,
    variant: ShapeVariantSpec | None,
) -> TaskFieldAliases:
    """Resolve field aliases for one rendered task record.

    Args:
        template: Base `L0` template.
        variant: Optional shape-variant override.

    Returns:
        Field aliases used for the record.
    """

    return variant.field_aliases if variant and variant.field_aliases is not None else template.field_aliases


def _resolved_optional_fields(
    template: L0TemplateSpec,
    variant: ShapeVariantSpec | None,
) -> list[str]:
    """Resolve optional task fields for one rendered record.

    Args:
        template: Base `L0` template.
        variant: Optional shape-variant override.

    Returns:
        Optional field names to emit for the record.
    """

    return (
        list(variant.optional_fields)
        if variant is not None and variant.optional_fields is not None
        else list(template.optional_fields)
    )


def _resolved_wrap_task_object(
    template: L0TemplateSpec,
    variant: ShapeVariantSpec | None,
) -> bool:
    """Resolve whether the record wraps task fields inside a nested object.

    Args:
        template: Base `L0` template.
        variant: Optional shape-variant override.

    Returns:
        `True` when the rendered record should wrap task fields.
    """

    return variant.wrap_task_object if variant and variant.wrap_task_object is not None else template.wrap_task_object


def _resolved_task_object_key(
    template: L0TemplateSpec,
    variant: ShapeVariantSpec | None,
) -> str:
    """Resolve the key used when wrapping task fields inside a nested object.

    Args:
        template: Base `L0` template.
        variant: Optional shape-variant override.

    Returns:
        Task-object key for the record.
    """

    return variant.task_object_key if variant and variant.task_object_key is not None else template.task_object_key


def _resolved_extra_fields(
    template: L0TemplateSpec,
    variant: ShapeVariantSpec | None,
) -> dict[str, Any]:
    """Resolve record-level extras for one rendered record.

    Args:
        template: Base `L0` template.
        variant: Optional shape-variant override.

    Returns:
        Deep-copied record-level extra fields.
    """

    extras = copy.deepcopy(template.extra_fields)
    if variant is None:
        return extras
    for field_name, field_value in variant.rare_extra_fields.items():
        extras[field_name] = copy.deepcopy(field_value)
    for field_name, field_value in variant.vendor_extra_fields.items():
        extras[field_name] = copy.deepcopy(field_value)
    return extras
