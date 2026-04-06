"""Seeded deterministic sampler for canonical synthetic benchmark scenarios."""

from __future__ import annotations

import hashlib
import json
import random

from ai_converter.synthetic_benchmark.scenario import (
    CanonicalScenario,
    CanonicalTask,
    DeterministicScenarioMetadata,
    SampledScenario,
    ScenarioSamplerConfig,
)

_TASK_NAME_FRAGMENTS = ("Plan", "Build", "Review", "Ship", "Deploy", "Audit")
_ASSIGNEES = ("Alex", "Dana", "Jordan", "Mina", "Riley", "Sam")
_TAG_POOL = ("backend", "frontend", "ops", "qa", "docs", "infra")


def sample_canonical_scenario(
    seed: int,
    config: ScenarioSamplerConfig | None = None,
) -> SampledScenario:
    """Sample one deterministic canonical scenario from a seed.

    Args:
        seed: Stable random seed controlling all sampling choices.
        config: Optional sampler configuration. Defaults to the baseline config.

    Returns:
        Canonical scenario plus reproducibility metadata.
    """

    resolved_config = config or ScenarioSamplerConfig()
    rng = random.Random(seed)
    tasks = [
        CanonicalTask(
            entity_id=f"T-{seed:02d}-{index + 1:02d}",
            name=f"{resolved_config.name_prefix} {index + 1} {_TASK_NAME_FRAGMENTS[rng.randrange(len(_TASK_NAME_FRAGMENTS))]}",
            status=resolved_config.status_cycle[rng.randrange(len(resolved_config.status_cycle))],
            duration_days=rng.randint(1, 10),
            assignee=_sample_assignee(rng, resolved_config.include_assignees),
            tags=_sample_tags(rng, resolved_config.include_tags),
        )
        for index in range(resolved_config.task_count)
    ]
    scenario = CanonicalScenario(
        scenario_id=f"{resolved_config.scenario_prefix}-{seed:04d}",
        source_template_id=resolved_config.source_template_id,
        tasks=tasks,
        notes=[f"seed:{seed}"],
    )
    return SampledScenario(
        scenario=scenario,
        reproducibility=DeterministicScenarioMetadata(
            seed=seed,
            config_hash=_config_hash(resolved_config),
        ),
    )


def _sample_assignee(rng: random.Random, include_assignees: bool) -> str | None:
    """Return an assignee when assignees are enabled for the sample.

    Args:
        rng: Deterministic random source for the current sample.
        include_assignees: Whether assignees may be emitted at all.

    Returns:
        Sampled assignee or `None`.
    """

    if not include_assignees or rng.random() < 0.35:
        return None
    return _ASSIGNEES[rng.randrange(len(_ASSIGNEES))]


def _sample_tags(rng: random.Random, include_tags: bool) -> list[str]:
    """Return deterministic tags for one synthetic task.

    Args:
        rng: Deterministic random source for the current sample.
        include_tags: Whether tags may be emitted.

    Returns:
        Sorted deterministic tag list.
    """

    if not include_tags:
        return []
    tag_count = rng.randint(0, 2)
    if tag_count == 0:
        return []
    return sorted(rng.sample(_TAG_POOL, k=tag_count))


def _config_hash(config: ScenarioSamplerConfig) -> str:
    """Compute a stable configuration hash for reproducibility metadata.

    Args:
        config: Sampler configuration to hash.

    Returns:
        Stable SHA-256 hex digest for the config payload.
    """

    payload = json.dumps(config.canonical_payload(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
