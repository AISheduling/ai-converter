"""Deterministic renderer from canonical scenario state to `L1` payloads."""

from __future__ import annotations

from typing import Any

from ai_converter.synthetic_benchmark.scenario import CanonicalScenario


def render_l1_payload(scenario: CanonicalScenario) -> dict[str, Any]:
    """Render one canonical scenario into a deterministic target-side payload.

    Args:
        scenario: Canonical scenario to render.

    Returns:
        Plain target-side dictionary suitable for structural validation.
    """

    return {
        "tasks": [
            {
                "id": task.entity_id,
                "name": task.name,
                "status": task.status,
                "duration_days": task.duration_days,
                "assignee": task.assignee,
                "tags": list(task.tags),
            }
            for task in scenario.tasks
        ]
    }
