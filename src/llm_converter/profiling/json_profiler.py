"""JSON flattening helpers used by profiling and fingerprinting."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def flatten_json_record(record: dict[str, Any]) -> dict[str, list[Any]]:
    """Flatten a nested JSON object into normalized path observations."""

    flattened: dict[str, list[Any]] = {}
    _walk_value(record, prefix="", out=flattened)
    return flattened


def profile_json(path: str | Path):
    """Build a profile report for a JSON or JSONL input."""

    from .report_builder import build_profile_report

    return build_profile_report(path)


def _walk_value(value: Any, prefix: str, out: dict[str, list[Any]]) -> None:
    """Recursively flatten nested JSON values into path observations."""

    if isinstance(value, dict):
        for key, nested in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            _walk_value(nested, next_prefix, out)
        return
    if isinstance(value, list):
        if prefix:
            out.setdefault(prefix, []).append(value)
        item_prefix = f"{prefix}[]" if prefix else "[]"
        if not value:
            out.setdefault(item_prefix, []).append([])
            return
        for item in value:
            _walk_value(item, item_prefix, out)
        return
    if prefix:
        out.setdefault(prefix, []).append(value)
