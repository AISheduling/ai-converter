"""Versioned canonical scenario models for deterministic synthetic bundles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CANONICAL_SCENARIO_VERSION = "1.0"
DETERMINISTIC_SCENARIO_GENERATOR_VERSION = "1.0"
TaskStatus = Literal["ready", "in_progress", "done"]


class CanonicalTask(BaseModel):
    """Canonical task entity used across deterministic synthetic scenarios."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    status: TaskStatus
    duration_days: int = Field(ge=1)
    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)


class CanonicalScenario(BaseModel):
    """Canonical scenario that serves as the single source of task truth."""

    model_config = ConfigDict(extra="forbid")

    version: str = CANONICAL_SCENARIO_VERSION
    scenario_id: str
    source_template_id: str = "task_schedule_v1"
    tasks: list[CanonicalTask] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible scenario payload.

        Returns:
            JSON-compatible payload for deterministic persistence.
        """

        return self.model_dump(mode="json")


class ScenarioSamplerConfig(BaseModel):
    """Configuration for seeded deterministic canonical scenario sampling."""

    model_config = ConfigDict(extra="forbid")

    task_count: int = Field(default=2, ge=1, le=10)
    include_assignees: bool = True
    include_tags: bool = True
    status_cycle: list[TaskStatus] = Field(
        default_factory=lambda: ["ready", "in_progress", "done"]
    )
    name_prefix: str = "Task"
    scenario_prefix: str = "scenario"
    source_template_id: str = "task_schedule_v1"

    @field_validator("status_cycle")
    @classmethod
    def _validate_status_cycle(cls, value: list[TaskStatus]) -> list[TaskStatus]:
        """Reject empty status cycles.

        Args:
            value: Candidate status labels used by the sampler.

        Returns:
            The original non-empty status list.

        Raises:
            ValueError: If the list is empty.
        """

        if not value:
            raise ValueError("status_cycle must not be empty")
        return value

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible sampler configuration payload.

        Returns:
            JSON-compatible configuration payload.
        """

        return self.model_dump(mode="json")


class DeterministicScenarioMetadata(BaseModel):
    """Reproducibility metadata produced by the deterministic sampler."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    generator_version: str = DETERMINISTIC_SCENARIO_GENERATOR_VERSION
    config_hash: str

    def canonical_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible reproducibility payload.

        Returns:
            JSON-compatible metadata payload.
        """

        return self.model_dump(mode="json")


class SampledScenario(BaseModel):
    """Canonical scenario plus reproducibility metadata from one sampler run."""

    model_config = ConfigDict(extra="forbid")

    scenario: CanonicalScenario
    reproducibility: DeterministicScenarioMetadata
