"""High-level helpers for applying deterministic synthetic drift specs."""

from __future__ import annotations

import copy
from typing import Any

from ai_converter.drift import classify_drift
from ai_converter.profiling import build_profile_report
from ai_converter.profiling.loaders import LoadedInput

from .models import AppliedDriftManifest, DriftSpec
from .operators import apply_operator_to_records, changed_paths_for_operator


def apply_drift_to_payload(
    payload: dict[str, Any] | list[dict[str, Any]],
    drift_spec: DriftSpec,
    *,
    records_key: str | None = None,
) -> tuple[dict[str, Any] | list[dict[str, Any]], AppliedDriftManifest]:
    """Apply one synthetic drift spec to an `L0` payload.

    Args:
        payload: Baseline `L0` payload to mutate.
        drift_spec: Drift specification to apply.
        records_key: Optional root key holding the record list for object-mode
            payloads.

    Returns:
        The drifted payload plus a machine-readable applied-drift manifest.
    """

    resolved_payload = copy.deepcopy(payload)
    records = _records_view(resolved_payload, records_key=records_key)
    changed_record_indexes: set[int] = set()
    for operator in drift_spec.operators:
        changed_record_indexes.update(apply_operator_to_records(records, operator))

    changed_paths = sorted(
        {
            path
            for operator in drift_spec.operators
            for path in changed_paths_for_operator(operator)
        }
    )
    baseline_report = build_profile_report(
        _loaded_input_from_payload(
            payload,
            path=f"synthetic://{drift_spec.drift_id}/base.json",
        )
    )
    candidate_report = build_profile_report(
        _loaded_input_from_payload(
            resolved_payload,
            path=f"synthetic://{drift_spec.drift_id}/candidate.json",
        )
    )
    drift_report = classify_drift(baseline_report, candidate_report)
    manifest = AppliedDriftManifest(
        drift_id=drift_spec.drift_id,
        drift_type=drift_spec.drift_type,
        severity=drift_spec.severity,
        compatibility_class=drift_report.classification,
        compatible=drift_report.compatible,
        operator_sequence=[operator.kind for operator in drift_spec.operators],
        changed_paths=changed_paths,
        changed_record_indexes=sorted(changed_record_indexes),
        notes=_manifest_notes(drift_spec, drift_report.classification),
        drift_report=drift_report,
    )
    return resolved_payload, manifest


def _records_view(
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    records_key: str | None,
) -> list[dict[str, Any]]:
    """Return the mutable list of records inside one rendered `L0` payload.

    Args:
        payload: Candidate `L0` payload.
        records_key: Optional known root key for object-mode payloads.

    Returns:
        Mutable list of rendered records.

    Raises:
        ValueError: If the payload does not contain a record list.
    """

    if isinstance(payload, list):
        return payload
    if records_key is not None:
        candidate = payload.get(records_key)
        if isinstance(candidate, list):
            return candidate
    for value in payload.values():
        if isinstance(value, list):
            return value
    raise ValueError("payload does not contain a record list")


def _loaded_input_from_payload(
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    path: str,
) -> LoadedInput:
    """Build an in-memory profiling input from one synthetic `L0` payload.

    Args:
        payload: Synthetic `L0` payload to profile.
        path: Stable synthetic source path label.

    Returns:
        In-memory profiling input for the candidate payload.
    """

    if isinstance(payload, list):
        return LoadedInput(
            kind="json",
            path=path,
            records=copy.deepcopy(payload),
            root_type="list",
        )
    return LoadedInput(
        kind="json",
        path=path,
        records=[copy.deepcopy(payload)],
        root_type="object",
    )


def _manifest_notes(
    drift_spec: DriftSpec,
    actual_classification: str,
) -> list[str]:
    """Build deterministic manifest notes for one applied drift spec.

    Args:
        drift_spec: Drift specification requested by the caller.
        actual_classification: Classification observed from the drift analyzer.

    Returns:
        Notes stored alongside the applied drift manifest.
    """

    notes = list(drift_spec.notes)
    if actual_classification != drift_spec.compatibility_class:
        notes.append(
            "Observed drift classification differed from the requested expectation: "
            f"{drift_spec.compatibility_class!r} -> {actual_classification!r}."
        )
    return notes
