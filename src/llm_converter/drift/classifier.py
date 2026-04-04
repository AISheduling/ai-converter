"""Deterministic drift classification built on profile and schema contracts."""

from __future__ import annotations

from difflib import SequenceMatcher

from llm_converter.profiling.models import FieldProfile, ProfileReport
from llm_converter.schema import SourceFieldSpec, SourceSchemaSpec

from .models import DriftClassification, DriftReport, FieldDrift, FieldSignature


def classify_drift(
    baseline_report: ProfileReport,
    candidate_report: ProfileReport,
    *,
    baseline_schema: SourceSchemaSpec | None = None,
    candidate_schema: SourceSchemaSpec | None = None,
    rename_similarity_threshold: float = 0.72,
) -> DriftReport:
    """Classify drift between two source descriptions deterministically.

    Args:
        baseline_report: Stable baseline profile.
        candidate_report: New profile to compare against the baseline.
        baseline_schema: Optional baseline schema contract for extra unit and
            cardinality context.
        candidate_schema: Optional candidate schema contract for extra unit and
            cardinality context.
        rename_similarity_threshold: Minimum name-similarity score used when
            pairing removed and added paths into compatible rename candidates.

    Returns:
        A deterministic drift report describing the comparison.
    """

    baseline_profiles = {field.path: field for field in baseline_report.field_profiles}
    candidate_profiles = {field.path: field for field in candidate_report.field_profiles}
    baseline_schema_fields = _schema_field_map(baseline_schema)
    candidate_schema_fields = _schema_field_map(candidate_schema)

    field_drifts: list[FieldDrift] = []
    notes: list[str] = []

    shared_paths = sorted(set(baseline_profiles) & set(candidate_profiles))
    added_paths = sorted(set(candidate_profiles) - set(baseline_profiles))
    removed_paths = sorted(set(baseline_profiles) - set(candidate_profiles))

    for path in shared_paths:
        baseline_signature = _signature_from_inputs(
            baseline_profiles[path],
            baseline_schema_fields.get(path),
        )
        candidate_signature = _signature_from_inputs(
            candidate_profiles[path],
            candidate_schema_fields.get(path),
        )
        reasons, classification = _classify_shared_signature(
            baseline_signature,
            candidate_signature,
        )
        if reasons:
            field_drifts.append(
                FieldDrift(
                    kind="changed",
                    baseline_path=path,
                    candidate_path=path,
                    classification=classification,
                    compatible=classification != "breaking_change",
                    reasons=reasons,
                    baseline_signature=baseline_signature,
                    candidate_signature=candidate_signature,
                )
            )

    rename_pairs = _match_renames(
        removed_paths,
        added_paths,
        baseline_profiles,
        candidate_profiles,
        baseline_schema_fields,
        candidate_schema_fields,
        rename_similarity_threshold=rename_similarity_threshold,
    )

    matched_removed = {baseline_path for baseline_path, _, _ in rename_pairs}
    matched_added = {candidate_path for _, candidate_path, _ in rename_pairs}

    for baseline_path, candidate_path, score in rename_pairs:
        field_drifts.append(
            FieldDrift(
                kind="renamed",
                baseline_path=baseline_path,
                candidate_path=candidate_path,
                classification="rename_compatible",
                compatible=True,
                reasons=[
                    "Removed baseline path and added candidate path have compatible type,"
                    " cardinality, and name similarity."
                ],
                score=round(score, 6),
                baseline_signature=_signature_from_inputs(
                    baseline_profiles[baseline_path],
                    baseline_schema_fields.get(baseline_path),
                ),
                candidate_signature=_signature_from_inputs(
                    candidate_profiles[candidate_path],
                    candidate_schema_fields.get(candidate_path),
                ),
            )
        )

    for path in added_paths:
        if path in matched_added:
            continue
        field_drifts.append(
            FieldDrift(
                kind="added",
                candidate_path=path,
                classification="additive_compatible",
                compatible=True,
                reasons=["New candidate path is additive and does not replace an existing baseline path."],
                candidate_signature=_signature_from_inputs(
                    candidate_profiles[path],
                    candidate_schema_fields.get(path),
                ),
            )
        )

    for path in removed_paths:
        if path in matched_removed:
            continue
        baseline_signature = _signature_from_inputs(
            baseline_profiles[path],
            baseline_schema_fields.get(path),
        )
        classification = (
            "breaking_change" if baseline_signature.present_ratio >= 0.95 else "semantic_change"
        )
        field_drifts.append(
            FieldDrift(
                kind="removed",
                baseline_path=path,
                classification=classification,
                compatible=False,
                reasons=["Baseline path disappeared without a compatible rename candidate."],
                baseline_signature=baseline_signature,
            )
        )

    overall = _overall_classification(field_drifts)
    if overall == "no_change":
        notes.append("Baseline and candidate profiles are structurally equivalent for TASK-05 purposes.")
    elif overall == "rename_compatible":
        notes.append("All detected drift can be explained by compatible renames and additive fields.")
    elif overall == "additive_compatible":
        notes.append("Only additive compatible drift was detected.")

    return DriftReport(
        classification=overall,
        compatible=overall in {"no_change", "additive_compatible", "rename_compatible"},
        baseline_fingerprint=baseline_report.schema_fingerprint,
        candidate_fingerprint=candidate_report.schema_fingerprint,
        field_drifts=sorted(
            field_drifts,
            key=lambda drift: (
                drift.baseline_path or drift.candidate_path or "",
                drift.kind,
            ),
        ),
        notes=notes,
    )


def _schema_field_map(schema: SourceSchemaSpec | None) -> dict[str, SourceFieldSpec]:
    """Build a path-indexed source schema field map.

    Args:
        schema: Optional source schema contract.

    Returns:
        A mapping from canonical path to field specification.
    """

    if schema is None:
        return {}
    return {field.path: field for field in schema.fields}


def _signature_from_inputs(
    profile: FieldProfile,
    schema_field: SourceFieldSpec | None,
) -> FieldSignature:
    """Build one deterministic comparison signature.

    Args:
        profile: Field profile derived from profiling.
        schema_field: Optional schema contract entry for the same path.

    Returns:
        A deterministic field signature.
    """

    dominant_type = _dominant_type(profile)
    enum_values = [entry.value for entry in profile.top_values]
    cardinality = (
        schema_field.cardinality
        if schema_field is not None
        else ("many" if profile.path.endswith("[]") or (profile.max_array_length or 0) > 1 else "one")
    )
    return FieldSignature(
        path=profile.path,
        dominant_type=dominant_type,
        present_ratio=profile.present_ratio,
        null_ratio=profile.null_ratio,
        cardinality=cardinality,
        enum_values=enum_values,
        unit=schema_field.unit if schema_field is not None else None,
    )


def _dominant_type(profile: FieldProfile) -> str | None:
    """Return the dominant observed type for one field profile.

    Args:
        profile: Field profile to inspect.

    Returns:
        The most common normalized type name, or ``None`` when the profile has
        no observed types.
    """

    if not profile.observed_types:
        return None
    dominant = sorted(
        profile.observed_types,
        key=lambda entry: (-entry.count, entry.type_name),
    )[0]
    return dominant.type_name


def _classify_shared_signature(
    baseline_signature: FieldSignature,
    candidate_signature: FieldSignature,
) -> tuple[list[str], DriftClassification]:
    """Compare shared-path signatures and derive drift severity.

    Args:
        baseline_signature: Baseline signature for the shared path.
        candidate_signature: Candidate signature for the shared path.

    Returns:
        A tuple of human-readable reasons and the derived classification.
    """

    reasons: list[str] = []
    severity: DriftClassification = "no_change"

    if baseline_signature.cardinality != candidate_signature.cardinality:
        reasons.append(
            "Cardinality changed from "
            f"{baseline_signature.cardinality!r} to {candidate_signature.cardinality!r}."
        )
        severity = "breaking_change"

    if baseline_signature.dominant_type != candidate_signature.dominant_type:
        reasons.append(
            "Dominant type changed from "
            f"{baseline_signature.dominant_type!r} to {candidate_signature.dominant_type!r}."
        )
        if _is_numeric_pair(baseline_signature.dominant_type, candidate_signature.dominant_type):
            severity = _max_classification(severity, "semantic_change")
        else:
            severity = "breaking_change"

    if baseline_signature.present_ratio >= 0.95 and candidate_signature.present_ratio < 0.95:
        reasons.append("A near-required field became partially missing in the candidate profile.")
        severity = "breaking_change"

    if (
        baseline_signature.unit is not None
        and candidate_signature.unit is not None
        and baseline_signature.unit != candidate_signature.unit
    ):
        reasons.append(
            f"Unit changed from {baseline_signature.unit!r} to {candidate_signature.unit!r}."
        )
        severity = _max_classification(severity, "semantic_change")

    if _enum_changed_significantly(baseline_signature, candidate_signature):
        reasons.append("Enum-like top values changed significantly for a shared path.")
        severity = _max_classification(severity, "semantic_change")

    return reasons, severity


def _match_renames(
    removed_paths: list[str],
    added_paths: list[str],
    baseline_profiles: dict[str, FieldProfile],
    candidate_profiles: dict[str, FieldProfile],
    baseline_schema_fields: dict[str, SourceFieldSpec],
    candidate_schema_fields: dict[str, SourceFieldSpec],
    *,
    rename_similarity_threshold: float,
) -> list[tuple[str, str, float]]:
    """Greedily pair removed and added paths into compatible rename candidates.

    Args:
        removed_paths: Paths missing from the candidate profile.
        added_paths: Paths only present in the candidate profile.
        baseline_profiles: Baseline profile map by path.
        candidate_profiles: Candidate profile map by path.
        baseline_schema_fields: Baseline source-schema fields by path.
        candidate_schema_fields: Candidate source-schema fields by path.
        rename_similarity_threshold: Minimum score required for a rename match.

    Returns:
        Greedy rename matches as ``(baseline_path, candidate_path, score)`` tuples.
    """

    candidates: list[tuple[float, str, str]] = []
    for baseline_path in removed_paths:
        baseline_signature = _signature_from_inputs(
            baseline_profiles[baseline_path],
            baseline_schema_fields.get(baseline_path),
        )
        for candidate_path in added_paths:
            candidate_signature = _signature_from_inputs(
                candidate_profiles[candidate_path],
                candidate_schema_fields.get(candidate_path),
            )
            score = _rename_score(baseline_signature, candidate_signature)
            if score < rename_similarity_threshold:
                continue
            if baseline_signature.dominant_type != candidate_signature.dominant_type:
                continue
            if baseline_signature.cardinality != candidate_signature.cardinality:
                continue
            candidates.append((score, baseline_path, candidate_path))

    matches: list[tuple[str, str, float]] = []
    used_removed: set[str] = set()
    used_added: set[str] = set()
    for score, baseline_path, candidate_path in sorted(
        candidates,
        key=lambda item: (-item[0], item[1], item[2]),
    ):
        if baseline_path in used_removed or candidate_path in used_added:
            continue
        used_removed.add(baseline_path)
        used_added.add(candidate_path)
        matches.append((baseline_path, candidate_path, score))
    return matches


def _rename_score(
    baseline_signature: FieldSignature,
    candidate_signature: FieldSignature,
) -> float:
    """Compute a deterministic compatibility score for one rename pair.

    Args:
        baseline_signature: Baseline signature for a removed path.
        candidate_signature: Candidate signature for an added path.

    Returns:
        A score in the ``[0.0, 1.0]`` range.
    """

    baseline_name = _normalized_name(_leaf_name(baseline_signature.path))
    candidate_name = _normalized_name(_leaf_name(candidate_signature.path))
    name_similarity = SequenceMatcher(a=baseline_name, b=candidate_name).ratio()
    presence_similarity = 1.0 - abs(
        baseline_signature.present_ratio - candidate_signature.present_ratio
    )
    null_similarity = 1.0 - abs(
        baseline_signature.null_ratio - candidate_signature.null_ratio
    )
    return (name_similarity * 0.7) + (presence_similarity * 0.2) + (null_similarity * 0.1)


def _leaf_name(path: str) -> str:
    """Return the leaf segment for one dotted or array-marked path.

    Args:
        path: Canonical source path.

    Returns:
        The last path segment without array markers.
    """

    return path.replace("[]", "").split(".")[-1]


def _normalized_name(name: str) -> str:
    """Normalize a field or path leaf for similarity scoring.

    Args:
        name: Raw leaf name.

    Returns:
        A lower-cased alpha-numeric string without separators.
    """

    return "".join(character for character in name.lower() if character.isalnum())


def _enum_changed_significantly(
    baseline_signature: FieldSignature,
    candidate_signature: FieldSignature,
) -> bool:
    """Check whether enum-like top values changed materially.

    Args:
        baseline_signature: Baseline signature.
        candidate_signature: Candidate signature.

    Returns:
        ``True`` when the overlap between enum-like values is very low.
    """

    baseline_values = {value for value in baseline_signature.enum_values if value}
    candidate_values = {value for value in candidate_signature.enum_values if value}
    if not baseline_values or not candidate_values:
        return False
    if baseline_signature.dominant_type != "str" or candidate_signature.dominant_type != "str":
        return False
    intersection = len(baseline_values & candidate_values)
    union = len(baseline_values | candidate_values)
    if union == 0:
        return False
    return (intersection / union) < 0.25


def _is_numeric_pair(left: str | None, right: str | None) -> bool:
    """Return whether both type labels are numeric-like.

    Args:
        left: First dominant type.
        right: Second dominant type.

    Returns:
        ``True`` when both labels are in the numeric type family.
    """

    numeric_types = {"int", "float"}
    return left in numeric_types and right in numeric_types


def _max_classification(
    current: DriftClassification,
    candidate: DriftClassification,
) -> DriftClassification:
    """Return the more severe of two drift classifications.

    Args:
        current: Current severity.
        candidate: Candidate severity.

    Returns:
        The more severe classification.
    """

    ordering = {
        "no_change": 0,
        "additive_compatible": 1,
        "rename_compatible": 2,
        "semantic_change": 3,
        "breaking_change": 4,
    }
    return current if ordering[current] >= ordering[candidate] else candidate


def _overall_classification(field_drifts: list[FieldDrift]) -> DriftClassification:
    """Derive one overall classification from per-field drift records.

    Args:
        field_drifts: Individual field-level drift records.

    Returns:
        One top-level drift classification.
    """

    if not field_drifts:
        return "no_change"
    classifications = {drift.classification for drift in field_drifts}
    if "breaking_change" in classifications:
        return "breaking_change"
    if "semantic_change" in classifications:
        return "semantic_change"
    if "rename_compatible" in classifications:
        return "rename_compatible"
    return "additive_compatible"
