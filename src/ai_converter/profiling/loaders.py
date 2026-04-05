"""Normalized loaders for CSV, JSON, and JSONL scheduling inputs."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def normalize_name(name: str) -> str:
    """Normalize source field names into stable internal path segments.

    Args:
        name: Raw source field name from an input payload.

    Returns:
        Stable lowercase identifier used for normalized paths.
    """

    collapsed = "_".join(name.strip().split())
    return collapsed.lower()


@dataclass(slots=True)
class LoadedDataset:
    """Normalized dataset contents used by report builders."""

    source_name: str
    source_format: str
    root_type: str
    records: list[dict[str, Any]]
    original_names: dict[str, set[str]]
    normalized_field_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LoadedInput:
    """In-memory input used by tests and higher-level orchestration."""

    kind: str
    path: str | None
    records: list[dict[str, Any]]
    original_names: dict[str, set[str]] = field(default_factory=dict)
    normalized_field_aliases: dict[str, str] = field(default_factory=dict)
    root_type: str = "rows"


def load_dataset(path: str | Path) -> LoadedDataset:
    """Load a supported file into normalized record dictionaries.

    Args:
        path: Repository-local path to a CSV, JSON, or JSONL source file.

    Returns:
        Normalized dataset representation for the input file.
    """

    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(source_path)
    if suffix == ".json":
        return _load_json(source_path)
    if suffix == ".jsonl":
        return _load_jsonl(source_path)
    raise ValueError(f"Unsupported source format: {source_path.suffix}")


def _load_csv(path: Path) -> LoadedDataset:
    """Load a CSV file into normalized row dictionaries.

    Args:
        path: Path to the CSV file to load.

    Returns:
        Loaded dataset with normalized CSV records and alias metadata.
    """

    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample or ",")
        except csv.Error:
            dialect = csv.get_dialect("excel")
        reader = csv.DictReader(handle, dialect=dialect)
        if reader.fieldnames is None:
            raise ValueError("CSV source must contain a header row")

        fieldnames = list(reader.fieldnames)
        normalized_headers = _normalized_csv_headers(fieldnames)
        normalized_fieldnames = [normalized for normalized, _ in normalized_headers]
        original_names = {
            normalized: {original}
            for normalized, original in normalized_headers
        }

        records: list[dict[str, Any]] = []
        for row in reader:
            normalized_row: dict[str, Any] = {}
            for original, normalized in zip(fieldnames, normalized_fieldnames, strict=True):
                value = row.get(original)
                normalized_row[normalized] = None if value == "" else value
            records.append(normalized_row)

    return LoadedDataset(
        source_name=path.name,
        source_format="csv",
        root_type="rows",
        records=records,
        original_names=original_names,
        normalized_field_aliases={name: name for name in normalized_fieldnames},
    )


def _normalized_csv_headers(fieldnames: Sequence[str]) -> list[tuple[str, str]]:
    """Return normalized CSV header pairs, rejecting collisions up front.

    Args:
        fieldnames: Raw CSV header names as reported by ``csv.DictReader``.

    Returns:
        Ordered ``(normalized_name, original_name)`` pairs for each CSV column.

    Raises:
        ValueError: If two or more headers normalize to the same internal name.
    """

    normalized_headers = [(normalize_name(original), original) for original in fieldnames]
    collisions: dict[str, list[str]] = {}
    seen: dict[str, list[str]] = {}
    for normalized, original in normalized_headers:
        originals = seen.setdefault(normalized, [])
        originals.append(original)
        if len(originals) > 1:
            collisions[normalized] = originals

    if collisions:
        details = "; ".join(
            f"{normalized}: {', '.join(repr(name) for name in originals)}"
            for normalized, originals in sorted(collisions.items())
        )
        raise ValueError(f"CSV headers must normalize to unique field names; collisions: {details}")

    return normalized_headers


def _load_json(path: Path) -> LoadedDataset:
    """Load a JSON file into normalized records and root metadata.

    Args:
        path: Path to the JSON file to load.

    Returns:
        Loaded dataset with normalized JSON records and root metadata.
    """

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    records, root_type = _records_from_json_payload(payload)
    return LoadedDataset(
        source_name=path.name,
        source_format="json",
        root_type=root_type,
        records=records,
        original_names={},
        normalized_field_aliases={},
    )


def _load_jsonl(path: Path) -> LoadedDataset:
    """Load a JSONL file into normalized row dictionaries.

    Args:
        path: Path to the JSONL file to load.

    Returns:
        Loaded dataset with normalized JSONL records.
    """

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError("JSONL input must contain one object per line")
            records.append(payload)
    return LoadedDataset(
        source_name=path.name,
        source_format="jsonl",
        root_type="rows",
        records=records,
        original_names={},
        normalized_field_aliases={},
    )


def _records_from_json_payload(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """Normalize a JSON payload into records plus a root-type label.

    Args:
        payload: Parsed JSON payload to normalize.

    Returns:
        Tuple of normalized record dictionaries and the inferred root type.
    """

    if isinstance(payload, dict):
        return [payload], "object"
    if isinstance(payload, list):
        if all(isinstance(item, dict) for item in payload):
            return list(payload), "list"
        return [{"value": payload}], "list"
    return [{"value": payload}], "object"
