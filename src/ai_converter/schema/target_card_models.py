"""Compact Pydantic models describing the fixed L1 target schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TargetFieldCard(BaseModel):
    """Compact prompt-oriented representation of one target schema field."""

    name: str
    path: str
    type_label: str
    required: bool
    description: str | None = None
    default: Any = None
    enum_values: list[str] = Field(default_factory=list)
    children: list["TargetFieldCard"] = Field(default_factory=list)


class TargetSchemaCard(BaseModel):
    """Compact representation of an L1 Pydantic model tree."""

    model_name: str
    module_name: str
    description: str | None = None
    fields: list[TargetFieldCard] = Field(default_factory=list)
