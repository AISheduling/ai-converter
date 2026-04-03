"""Stable fingerprinting for structural profile characteristics."""

from __future__ import annotations

import hashlib
import json

from .models import FieldProfile, ProfileReport


def compute_profile_fingerprint(fields: list[FieldProfile]) -> str:
    """Hash only stable structural attributes of field profiles."""

    canonical_fields = [
        {
            "path": field.path,
            "types": {entry.type_name: entry.count for entry in field.observed_types},
            "present_ratio": round(field.present_ratio, 6),
            "null_ratio": round(field.null_ratio, 6),
            "candidate_id": field.candidate_id,
        }
        for field in sorted(fields, key=lambda item: item.path)
    ]
    payload = json.dumps(canonical_fields, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_report(report: ProfileReport) -> str:
    """Compute a fingerprint for a complete profile report."""

    return compute_profile_fingerprint(report.field_profiles)
