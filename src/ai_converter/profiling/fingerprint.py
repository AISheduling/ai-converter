"""Stable fingerprinting for structural profile characteristics.

The schema fingerprint is intentionally based on stable structure rather than
distribution-sensitive counters. It should change when field paths, observed
type sets, or structural nullability change, but not when identical records are
duplicated or other pure frequency changes occur.
"""

from __future__ import annotations

import hashlib
import json

from .models import FieldProfile, ProfileReport


def compute_profile_fingerprint(fields: list[FieldProfile]) -> str:
    """Hash only stable structural attributes of field profiles.

    The fingerprint excludes exact type counts, ratio values, and uniqueness
    heuristics because those reflect dataset distribution rather than schema
    structure.

    Args:
        fields: Field profiles to include in the deterministic fingerprint.

    Returns:
        Stable SHA-256 fingerprint for the provided field profiles.
    """

    canonical_fields = [
        {
            "path": field.path,
            "types": sorted({entry.type_name for entry in field.observed_types}),
            "optional": field.present_ratio < 1.0,
            "nullable": field.null_ratio > 0.0,
        }
        for field in sorted(fields, key=lambda item: item.path)
    ]
    payload = json.dumps(canonical_fields, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_report(report: ProfileReport) -> str:
    """Compute a fingerprint for a complete profile report.

    Args:
        report: Profile report whose field profiles should be hashed.

    Returns:
        Stable fingerprint for the report.
    """

    return compute_profile_fingerprint(report.field_profiles)
