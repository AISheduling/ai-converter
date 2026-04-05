"""Focused unit tests for MappingIR validation and fake-backed synthesis."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from ai_converter.llm import (
    FakeLLMAdapter,
    LLMCallBudgetExceededError,
    LLMCallBudgetPolicy,
    LLMUsage,
    FakeLLMReply,
    PromptEnvelope,
    PromptTemplateReference,
    render_mapping_ir_prompt,
    render_source_schema_prompt,
)
from ai_converter.mapping_ir import (
    MappingIR,
    MappingIRValidator,
    MappingStep,
    MappingSynthesizer,
    RepairCase,
    SourceReference,
    StepOperation,
    TargetAssignment,
    build_repair_prompt,
    select_best_candidate,
)
from ai_converter.profiling.report_builder import build_profile_report
from ai_converter.schema.source_spec_models import SourceFieldSpec, SourceSchemaSpec
from ai_converter.schema.target_card_builder import build_target_schema_card


ROOT = Path(__file__).resolve().parents[3]
PROFILE_FIXTURES = ROOT / "tests" / "fixtures" / "profiling"


class DemoTask(BaseModel):
    """Simple nested target model used by mapping-ir tests."""

    id: str = Field(description="Task identifier")
    name: str | None = Field(default=None, description="Task name")


class DemoTarget(BaseModel):
    """Simple root target model used by mapping-ir tests."""

    task: DemoTask
    status: str | None = Field(default=None, description="Task status")


def test_mapping_ir_validator_rejects_unknown_source_refs() -> None:
    """Verify that unknown source refs are rejected.

    Returns:
        None.
    """

    validator = MappingIRValidator()
    result = validator.validate(_candidate_with_unknown_source())

    assert result.valid is False
    assert any(issue.code == "unknown_source_ref" for issue in result.issues)


def test_mapping_ir_validator_rejects_conflicting_target_writes() -> None:
    """Verify that conflicting target assignments are rejected.

    Returns:
        None.
    """

    validator = MappingIRValidator()
    result = validator.validate(_candidate_with_conflicting_writes(), target_schema=_target_schema())

    assert result.valid is False
    assert any(issue.code == "conflicting_target_write" for issue in result.issues)


def test_mapping_ir_validator_accepts_valid_program() -> None:
    """Verify that a well-formed MappingIR program is accepted.

    Returns:
        None.
    """

    validator = MappingIRValidator()
    result = validator.validate(
        _partial_candidate(),
        source_schema=_source_schema(),
        target_schema=_target_schema(),
    )

    assert result.valid is True
    assert result.issues == []


def test_prompt_renderer_includes_required_sections() -> None:
    """Verify that prompt renderers embed the required payload sections.

    Returns:
        None.
    """

    report = build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=2)
    source_prompt = render_source_schema_prompt(report, budget=900, mode="compact", format_hint="project schedule")
    mapping_prompt = render_mapping_ir_prompt(_source_schema(), _target_schema(), conversion_hint="prefer explicit ids")

    assert "Evidence bundle" in source_prompt.user_prompt
    assert "Required output schema" in source_prompt.user_prompt
    assert "Allowed operations" in mapping_prompt.user_prompt
    assert "Source schema" in mapping_prompt.user_prompt
    assert "Target schema" in mapping_prompt.user_prompt


def test_synthesizer_ranks_candidates_by_validity_and_coverage() -> None:
    """Verify that ranking prefers valid, higher-coverage mapping candidates.

    Returns:
        None.
    """

    adapter = FakeLLMAdapter(
        structured_replies=[
            FakeLLMReply(parsed_payload=_candidate_with_unknown_source().model_dump(mode="json")),
            FakeLLMReply(parsed_payload=_partial_candidate().model_dump(mode="json")),
            FakeLLMReply(parsed_payload=_full_candidate().model_dump(mode="json")),
        ]
    )

    result = MappingSynthesizer(adapter).synthesize_mapping(
        _source_schema(),
        _target_schema(),
        candidate_count=3,
    )

    assert result.best_index == 2
    assert result.best_candidate is not None
    assert {assignment.target_path for assignment in result.best_candidate.assignments} == {"status", "task.id", "task.name"}
    assert result.candidates[0].ranked.coverage_ratio > result.candidates[1].ranked.coverage_ratio


def test_synthesizer_tracks_shared_llm_budget_across_schema_and_mapping() -> None:
    """Verify that schema and mapping calls share one centralized budget ledger.

    Returns:
        None.
    """

    adapter = FakeLLMAdapter(
        structured_replies=[
            FakeLLMReply(
                parsed_payload=_source_schema().model_dump(mode="json"),
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
            FakeLLMReply(
                parsed_payload=_partial_candidate().model_dump(mode="json"),
                usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
            ),
            FakeLLMReply(
                parsed_payload=_full_candidate().model_dump(mode="json"),
                usage=LLMUsage(prompt_tokens=14, completion_tokens=7, total_tokens=21),
            ),
        ]
    )
    synthesizer = MappingSynthesizer(
        adapter,
        budget_policy=LLMCallBudgetPolicy(schema=1, mapping=2, repair=1),
    )

    schema_response = synthesizer.synthesize_source_schema(
        build_profile_report(PROFILE_FIXTURES / "projects.json", sample_limit=2)
    )
    mapping_result = synthesizer.synthesize_mapping(
        schema_response.parsed or _source_schema(),
        _target_schema(),
        candidate_count=2,
    )

    assert schema_response.ok is True
    assert schema_response.metadata["llm_call_budget"]["total_used"] == 1
    assert schema_response.metadata["llm_call_budget"]["stages"]["schema"]["used"] == 1
    assert mapping_result.budget_accounting is not None
    assert mapping_result.budget_accounting.total_limit == 4
    assert mapping_result.budget_accounting.total_used == 3
    assert mapping_result.budget_accounting.total_remaining == 1
    assert mapping_result.budget_accounting.stages["schema"].used == 1
    assert mapping_result.budget_accounting.stages["mapping"].used == 2
    assert mapping_result.budget_accounting.stages["repair"].used == 0
    assert [record.stage for record in mapping_result.budget_accounting.calls] == ["schema", "mapping", "mapping"]
    assert [call.metadata.get("candidate_index") for call in adapter.calls[1:]] == [0, 1]


def test_synthesizer_stops_before_exceeding_mapping_budget() -> None:
    """Verify that mapping synthesis fails before making a budget-breaking call.

    Returns:
        None.
    """

    adapter = FakeLLMAdapter(
        structured_replies=[
            FakeLLMReply(parsed_payload=_partial_candidate().model_dump(mode="json")),
            FakeLLMReply(parsed_payload=_full_candidate().model_dump(mode="json")),
            FakeLLMReply(parsed_payload=_full_candidate().model_dump(mode="json")),
        ]
    )
    synthesizer = MappingSynthesizer(
        adapter,
        budget_policy=LLMCallBudgetPolicy(schema=0, mapping=2, repair=0),
    )

    with pytest.raises(LLMCallBudgetExceededError) as exc_info:
        synthesizer.synthesize_mapping(
            _source_schema(),
            _target_schema(),
            candidate_count=3,
        )

    snapshot = exc_info.value.snapshot

    assert exc_info.value.stage == "mapping"
    assert len(adapter.calls) == 2
    assert [call.metadata.get("candidate_index") for call in adapter.calls] == [0, 1]
    assert snapshot.total_used == 2
    assert snapshot.total_remaining == 0
    assert snapshot.stages["mapping"].used == 2
    assert snapshot.stages["mapping"].remaining == 0
    assert [record.index for record in snapshot.calls] == [1, 2]


def test_fake_llm_adapter_supports_structured_outputs() -> None:
    """Verify that the fake adapter validates and returns structured outputs.

    Returns:
        None.
    """

    prompt = PromptEnvelope(
        name="demo",
        version="v1",
        system_prompt="system",
        user_prompt="user",
        reference=PromptTemplateReference("demo", "v1", "system.txt", "user.txt"),
    )
    adapter = FakeLLMAdapter(structured_replies=[FakeLLMReply(parsed_payload=_partial_candidate().model_dump(mode="json"))])

    response = adapter.generate_structured(prompt, schema=MappingIR, metadata={"scenario": "structured"})

    assert response.ok is True
    assert response.parsed is not None
    assert isinstance(response.parsed, MappingIR)
    assert adapter.calls[0].schema_name == "MappingIR"


def test_repair_prompt_contains_failure_context() -> None:
    """Verify that repair prompts contain the failing context and diff.

    Returns:
        None.
    """

    prompt = build_repair_prompt(
        _full_candidate(),
        RepairCase(
            failing_fixture={"task_name": "Plan", "status_text": "ready"},
            expected={"task": {"id": "T-1", "name": "Plan"}, "status": "ready"},
            actual={"task": {"id": "T-1", "name": None}, "status": "ready"},
            error_log="AssertionError: task.name missing",
            problematic_rules=["assign-task-name"],
        ),
    )

    assert "AssertionError: task.name missing" in prompt.user_prompt
    assert '"task_name": "Plan"' in prompt.user_prompt
    assert "EXPECTED vs ACTUAL" in prompt.user_prompt
    assert "assign-task-name" in prompt.user_prompt


def test_candidate_aggregation_is_order_invariant() -> None:
    """Verify that deterministic tie-breaking is input-order invariant.

    Returns:
        None.
    """

    first = select_best_candidate(
        [_tie_candidate_alpha(), _tie_candidate_beta()],
        source_schema=_source_schema(),
        target_schema=_target_schema(),
    )
    second = select_best_candidate(
        [_tie_candidate_beta(), _tie_candidate_alpha()],
        source_schema=_source_schema(),
        target_schema=_target_schema(),
    )

    assert first is not None
    assert second is not None
    assert first.fingerprint == second.fingerprint


def _source_schema() -> SourceSchemaSpec:
    """Build a deterministic source schema used by mapping-ir tests.

    Returns:
        Source schema contract for the focused mapping-ir tests.
    """

    return SourceSchemaSpec(
        source_name="demo",
        source_format="json",
        root_type="list",
        fields=[
            SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str"),
            SourceFieldSpec(path="task_name", semantic_name="task_name", dtype="str"),
            SourceFieldSpec(path="status_text", semantic_name="status_text", dtype="str"),
        ],
    )


def _target_schema():
    """Build a compact target schema card used by mapping-ir tests.

    Returns:
        Compact target schema card for the focused mapping-ir tests.
    """

    return build_target_schema_card(DemoTarget)


def _source_refs() -> list[SourceReference]:
    """Build canonical source references for test programs.

    Returns:
        Canonical source references for the focused mapping-ir tests.
    """

    return [
        SourceReference(id="src_task_id", path="task_id", dtype="str"),
        SourceReference(id="src_task_name", path="task_name", dtype="str"),
        SourceReference(id="src_status", path="status_text", dtype="str"),
    ]


def _partial_candidate() -> MappingIR:
    """Build a valid candidate with partial target coverage.

    Returns:
        Valid mapping program with partial target coverage.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
        ],
    )


def _full_candidate() -> MappingIR:
    """Build a valid candidate with broader target coverage.

    Returns:
        Valid mapping program with broader target coverage.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(id="copy_status", operation=StepOperation(kind="copy", source_ref="src_status")),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
            TargetAssignment(step_id="copy_status", target_path="status"),
        ],
    )


def _candidate_with_unknown_source() -> MappingIR:
    """Build an invalid candidate that references an unknown source ref.

    Returns:
        Invalid mapping program with an unknown source reference.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="missing_ref"))],
        assignments=[TargetAssignment(step_id="copy_task_name", target_path="task.name")],
    )


def _candidate_with_conflicting_writes() -> MappingIR:
    """Build an invalid candidate with conflicting target writes.

    Returns:
        Invalid mapping program with conflicting target assignments.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(id="copy_status", operation=StepOperation(kind="copy", source_ref="src_status")),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
            TargetAssignment(step_id="copy_status", target_path="task.name"),
        ],
    )


def _tie_candidate_alpha() -> MappingIR:
    """Build one valid tie candidate for deterministic ordering tests.

    Returns:
        Valid mapping program used for deterministic tie-breaking tests.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[
            MappingStep(id="alpha_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="alpha_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
        ],
        assignments=[
            TargetAssignment(step_id="alpha_task_id", target_path="task.id"),
            TargetAssignment(step_id="alpha_task_name", target_path="task.name"),
        ],
    )


def _tie_candidate_beta() -> MappingIR:
    """Build another valid tie candidate for deterministic ordering tests.

    Returns:
        Another valid mapping program used for deterministic tie-breaking tests.
    """

    return MappingIR(
        source_refs=_source_refs(),
        steps=[
            MappingStep(id="beta_task_name", operation=StepOperation(kind="rename", source_ref="src_task_name")),
            MappingStep(id="beta_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
        ],
        assignments=[
            TargetAssignment(step_id="beta_task_id", target_path="task.id"),
            TargetAssignment(step_id="beta_task_name", target_path="task.name"),
        ],
    )
