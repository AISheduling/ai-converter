"""CSV helpers for deterministic profiling."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def flatten_csv_record(record: dict[str, Any]) -> dict[str, list[Any]]:
    """Represent a CSV row in the same path-to-values shape as JSON records.

    Args:
        record: Normalized CSV row keyed by column name.

    Returns:
        Path-to-values mapping compatible with the JSON flattener.
    """

    return {key: [value] for key, value in record.items()}


def profile_csv(path: str | Path):
    """Build a profile report for a CSV input.

    Args:
        path: Repository-local path to the CSV file to profile.

    Returns:
        Normalized profile report for the CSV input.
    """

    from .report_builder import build_profile_report

    return build_profile_report(path)
