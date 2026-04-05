"""Shared helpers for deterministic profiling type labels."""

from __future__ import annotations

from typing import Any


def python_value_type_label(value: Any) -> str:
    """Return the normalized type label used across profiling helpers."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "str"
