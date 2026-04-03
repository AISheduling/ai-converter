"""CSV helpers for deterministic profiling."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def flatten_csv_record(record: dict[str, Any]) -> dict[str, list[Any]]:
    """Represent a CSV row in the same path-to-values shape as JSON records."""

    return {key: [value] for key, value in record.items()}


def profile_csv(path: str | Path):
    """Build a profile report for a CSV input."""

    from .report_builder import build_profile_report

    return build_profile_report(path)
