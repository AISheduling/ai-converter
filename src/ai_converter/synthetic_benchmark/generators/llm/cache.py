"""Deterministic cache helpers for accepted synthetic template generations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_converter.llm.protocol import PromptEnvelope
from ai_converter.synthetic_benchmark.templates import L0TemplateSpec

from .models import AcceptedTemplateCacheEntry


def canonical_json_hash(payload: Any) -> str:
    """Hash one JSON-compatible payload deterministically.

    Args:
        payload: JSON-compatible payload to hash.

    Returns:
        Stable SHA-256 hex digest.
    """

    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_prompt_hash(prompt: PromptEnvelope) -> str:
    """Build a deterministic hash for one rendered prompt envelope.

    Args:
        prompt: Rendered prompt envelope.

    Returns:
        Stable prompt hash.
    """

    return canonical_json_hash(prompt.to_dict())


def build_cache_key(
    *,
    prompt_hash: str,
    llm_model_config: dict[str, Any],
    cache_namespace: str,
) -> str:
    """Build one deterministic cache key for a generation request.

    Args:
        prompt_hash: Hash of the rendered prompt surface.
        llm_model_config: Model-selection and inference knobs.
        cache_namespace: Logical namespace for segregating caches.

    Returns:
        Stable cache key.
    """

    return canonical_json_hash(
        {
            "cache_namespace": cache_namespace,
            "prompt_hash": prompt_hash,
            "llm_model_config": llm_model_config,
        }
    )


def template_fingerprint(template: L0TemplateSpec) -> str:
    """Build a structural fingerprint for one accepted template.

    The fingerprint intentionally ignores `template_id` so that trivial renames
    do not bypass the diversity gate.

    Args:
        template: Resolved template to fingerprint.

    Returns:
        Stable structural fingerprint.
    """

    payload = template.canonical_payload()
    payload.pop("template_id", None)
    return canonical_json_hash(payload)


class AcceptedTemplateCache:
    """Read and write accepted-template cache entries."""

    def load(self, root_dir: str | Path, cache_key: str) -> AcceptedTemplateCacheEntry | None:
        """Load one accepted-template entry from disk.

        Args:
            root_dir: Cache root directory.
            cache_key: Cache key to look up.

        Returns:
            Parsed cache entry or `None` when absent.
        """

        path = self._entry_path(root_dir, cache_key)
        if not path.exists():
            return None
        return AcceptedTemplateCacheEntry.model_validate_json(path.read_text(encoding="utf-8"))

    def write(
        self,
        root_dir: str | Path,
        entry: AcceptedTemplateCacheEntry,
    ) -> Path:
        """Persist one accepted-template cache entry.

        Args:
            root_dir: Cache root directory.
            entry: Cache entry to serialize.

        Returns:
            Concrete path written.
        """

        path = self._entry_path(root_dir, entry.cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry.canonical_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _entry_path(root_dir: str | Path, cache_key: str) -> Path:
        """Return the deterministic file path for one cache key.

        Args:
            root_dir: Cache root directory.
            cache_key: Cache key that identifies the entry.

        Returns:
            Deterministic JSON path.
        """

        return Path(root_dir) / f"{cache_key}.json"
