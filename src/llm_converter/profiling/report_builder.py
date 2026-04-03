"""Profile report builder shared by CSV and JSON profilers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .csv_profiler import flatten_csv_record
from .fingerprint import compute_profile_fingerprint
from .json_profiler import flatten_json_record
from .loaders import LoadedDataset, LoadedInput, load_dataset
from .models import DatasetMetadata, FieldProfile, ObservedTypeCount, ProfileReport, ScalarSummary, SourceInfo, ValueCount
from .sampling import select_representative_samples


def build_profile_report(path_or_input: str | Path | LoadedInput, *, sample_limit: int = 3) -> ProfileReport:
    """Load a dataset and return its normalized profile report."""

    dataset = _ensure_loaded_dataset(path_or_input)
    flattened_records = _flatten_records(dataset)
    fields = _build_field_profiles(dataset, flattened_records)
    samples = select_representative_samples(flattened_records, dataset.records, limit=sample_limit)
    return ProfileReport(
        source=SourceInfo(
            kind=dataset.source_format,  # type: ignore[arg-type]
            path=str(path_or_input) if isinstance(path_or_input, (str, Path)) else path_or_input.path,
            normalized_field_aliases=dataset.normalized_field_aliases,
        ),
        record_count=len(dataset.records),
        metadata=DatasetMetadata(
            source_name=dataset.source_name,
            source_format=dataset.source_format,  # type: ignore[arg-type]
            root_type=dataset.root_type,  # type: ignore[arg-type]
            record_count=len(dataset.records),
        ),
        field_profiles=fields,
        representative_samples=samples,
        schema_fingerprint=compute_profile_fingerprint(fields),
    )


def _ensure_loaded_dataset(path_or_input: str | Path | LoadedInput) -> LoadedDataset:
    if isinstance(path_or_input, LoadedInput):
        return LoadedDataset(
            source_name="in-memory" if path_or_input.path else "in-memory",
            source_format=path_or_input.kind,
            root_type=path_or_input.root_type,
            records=sorted(path_or_input.records, key=_stable_repr),
            original_names=path_or_input.original_names,
            normalized_field_aliases=path_or_input.normalized_field_aliases,
        )
    dataset = load_dataset(path_or_input)
    dataset.records = sorted(dataset.records, key=_stable_repr)
    return dataset


def _flatten_records(dataset: LoadedDataset) -> list[dict[str, list[Any]]]:
    if dataset.source_format == "csv":
        return [flatten_csv_record(record) for record in dataset.records]
    return [flatten_json_record(record) for record in dataset.records]


def _build_field_profiles(
    dataset: LoadedDataset,
    flattened_records: list[dict[str, list[Any]]],
) -> list[FieldProfile]:
    all_paths = sorted({path for record in flattened_records for path in record})
    profiles: list[FieldProfile] = []
    total_records = max(1, len(flattened_records))
    for path in all_paths:
        present_count = 0
        null_count = 0
        observed_types: Counter[str] = Counter()
        unique_values: set[str] = set()
        non_null_count = 0
        numeric_values: list[float] = []
        length_values: list[float] = []
        scalar_counts: Counter[str] = Counter()
        sample_values: set[str] = set()

        for record in flattened_records:
            values = record.get(path)
            if values is None:
                continue
            present_count += 1
            for value in values:
                type_name = _type_name(value)
                observed_types[type_name] += 1
                sample_values.add(_stable_repr(value))
                if value is None:
                    null_count += 1
                    continue
                non_null_count += 1
                unique_values.add(_stable_repr(value))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_values.append(float(value))
                if isinstance(value, (str, list)):
                    length_values.append(float(len(value)))
                if not isinstance(value, (dict, list)):
                    scalar_counts[_stable_repr(value)] += 1

        profiles.append(
            FieldProfile(
                path=path,
                original_names=sorted(dataset.original_names.get(path, {path})),
                observed_types=[
                    ObservedTypeCount(type_name=type_name, count=count)
                    for type_name, count in sorted(observed_types.items())
                ],
                present_ratio=present_count / total_records,
                null_ratio=(null_count / present_count) if present_count else 0.0,
                unique_ratio=(len(unique_values) / non_null_count) if non_null_count else 0.0,
                numeric_range=_range_summary(numeric_values),
                length_range=_range_summary(length_values),
                max_array_length=_max_array_length(path, flattened_records),
                top_values=_top_values(scalar_counts),
                sample_values=sorted(sample_values)[:5],
                candidate_id=(
                    present_count == total_records
                    and non_null_count > 0
                    and (len(unique_values) / non_null_count) >= 0.95
                    and any(type_name in observed_types for type_name in ("str", "int"))
                ),
            )
        )
    return profiles


def _range_summary(values: list[float]) -> ScalarSummary | None:
    if not values:
        return None
    return ScalarSummary(min=min(values), max=max(values))


def _top_values(counter: Counter[str]) -> list[ValueCount]:
    return [
        ValueCount(value=value, count=count)
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]


def _type_name(value: Any) -> str:
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


def _stable_repr(value: Any) -> str:
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


def _max_array_length(path: str, flattened_records: list[dict[str, list[Any]]]) -> int | None:
    if not path.endswith("[]"):
        return None
    parent_path = path[:-2]
    lengths: list[int] = []
    for record in flattened_records:
        for value in record.get(parent_path, []):
            if isinstance(value, list):
                lengths.append(len(value))
    return max(lengths, default=None)
