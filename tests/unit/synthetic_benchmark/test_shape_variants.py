"""Focused unit tests for deterministic synthetic shape-variant rendering."""

from __future__ import annotations

from ai_converter.synthetic_benchmark import (
    L0TemplateSpec,
    ScenarioSamplerConfig,
    ShapeVariantPolicy,
    ShapeVariantSpec,
    render_l0_payload,
    sample_canonical_scenario,
)


def test_same_logical_type_can_have_different_field_sets() -> None:
    """Verify that one logical task type can render with heterogeneous shapes."""

    sampled = sample_canonical_scenario(
        21,
        ScenarioSamplerConfig(task_count=3, include_assignees=True, include_tags=True),
    )
    template = L0TemplateSpec(
        shape_variant_policy=ShapeVariantPolicy(
            assignment_mode="round_robin",
            variants=[
                ShapeVariantSpec(
                    variant_id="flat_vendor",
                    optional_fields=["assignee", "tags"],
                    vendor_extra_fields={"vendor_code": "alpha"},
                ),
                ShapeVariantSpec(
                    variant_id="wrapped_compact",
                    wrap_task_object=True,
                    task_object_key="task",
                    record_envelope_key="entry",
                    optional_fields=[],
                    rare_extra_fields={"shape": "compact"},
                ),
            ],
        )
    )

    payload = render_l0_payload(sampled.scenario, template)
    assert isinstance(payload, dict)

    records = payload["records"]
    assert "vendor_code" in records[0]
    assert "entry" in records[1]
    assert "task" in records[1]["entry"]
    assert set(records[0]) != set(records[1])
    assert records[0]["task_id"] == sampled.scenario.tasks[0].entity_id
    assert records[1]["entry"]["task"]["task_id"] == sampled.scenario.tasks[1].entity_id


def test_shape_variants_are_seeded_and_reproducible() -> None:
    """Verify that hash-based shape assignment is reproducible for a fixed seed."""

    template = L0TemplateSpec(
        shape_variant_policy=ShapeVariantPolicy(
            assignment_mode="hash",
            selection_salt="task-bench-02",
            variants=[
                ShapeVariantSpec(
                    variant_id="flat",
                    optional_fields=["assignee", "tags"],
                ),
                ShapeVariantSpec(
                    variant_id="wrapped",
                    wrap_task_object=True,
                    task_object_key="task",
                ),
            ],
        )
    )

    first = sample_canonical_scenario(33, ScenarioSamplerConfig(task_count=4))
    second = sample_canonical_scenario(33, ScenarioSamplerConfig(task_count=4))
    different = sample_canonical_scenario(34, ScenarioSamplerConfig(task_count=4))

    first_payload = render_l0_payload(first.scenario, template)
    second_payload = render_l0_payload(second.scenario, template)
    different_payload = render_l0_payload(different.scenario, template)

    assert first_payload == second_payload
    assert first_payload != different_payload
