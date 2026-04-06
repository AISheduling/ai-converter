"""Versioned template models for deterministic L0 surface rendering."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

L0_TEMPLATE_SPEC_VERSION = "1.0"
OptionalTaskField = Literal["assignee", "tags"]


class TaskFieldAliases(BaseModel):
    """Configurable alias surface for deterministic task-record rendering."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = "task_id"
    name: str = "task_name"
    status: str = "status_text"
    duration_days: str = "duration_days"
    assignee: str = "assignee"
    tags: str = "tags"


class L0TemplateSpec(BaseModel):
    """Template that controls how canonical tasks are packed into `L0` JSON."""

    model_config = ConfigDict(extra="forbid")

    version: str = L0_TEMPLATE_SPEC_VERSION
    template_id: str = "task_record_v1"
    root_mode: Literal["object", "list"] = "object"
    records_key: str = "records"
    wrap_task_object: bool = False
    task_object_key: str = "task"
    field_aliases: TaskFieldAliases = Field(default_factory=TaskFieldAliases)
    optional_fields: list[OptionalTaskField] = Field(
        default_factory=lambda: ["assignee", "tags"]
    )
    extra_fields: dict[str, Any] = Field(default_factory=dict)

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible template payload.

        Returns:
            JSON-compatible template payload.
        """

        return self.model_dump(mode="json")
