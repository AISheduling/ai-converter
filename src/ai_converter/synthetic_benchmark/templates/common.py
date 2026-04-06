"""Shared template contracts for deterministic synthetic `L0` rendering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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
