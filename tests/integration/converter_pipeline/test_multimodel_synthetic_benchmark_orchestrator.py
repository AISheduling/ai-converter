"""Offline integration test for the multi-model synthetic benchmark orchestrator."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ai_converter.mapping_ir import MappingIR, MappingIRValidator, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec, build_target_schema_card

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SCRIPT = ROOT / "examples" / "synthetic_benchmark" / "run_multimodel_orchestrator.py"


@dataclass(slots=True)
class _FakeUsage:
    """Fake usage payload returned by the injected OpenAI-like client."""

    input_tokens: int = 10
    output_tokens: int = 5
    total_tokens: int = 15


class _FakeOpenAIResponse:
    """Fake response object returned by the injected OpenAI-like client."""

    def __init__(self, *, output_text: str, output_parsed: Any) -> None:
        """Initialize the fake OpenAI response.

        Args:
            output_text: Raw text mirrored from the structured payload.
            output_parsed: Parsed payload returned by the fake response.

        Returns:
            None.
        """

        self.output_text = output_text
        self.output_parsed = output_parsed
        self.usage = _FakeUsage()
        self.output = []


class _QueuedResponsesAPI:
    """Queued fake ``responses`` namespace for offline example tests."""

    def __init__(self, responses: list[_FakeOpenAIResponse]) -> None:
        """Store the queued create responses.

        Args:
            responses: Ordered fake responses consumed by ``responses.create``.

        Returns:
            None.
        """

        self._responses = list(responses)
        self.create_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        """Return the next queued create response.

        Args:
            **kwargs: Request payload captured for later assertions.

        Returns:
            The next fake OpenAI response.
        """

        self.create_calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No queued fake responses remain for responses.create")
        return self._responses.pop(0)


class _QueuedOpenAIClient:
    """Fake OpenAI-like client injected into the orchestration script."""

    def __init__(self, responses: list[_FakeOpenAIResponse]) -> None:
        """Build the fake client with deterministic queued replies.

        Args:
            responses: Ordered fake responses returned by ``responses.create``.

        Returns:
            None.
        """

        self.responses = _QueuedResponsesAPI(responses)


def test_multimodel_orchestrator_runs_offline() -> None:
    """Verify that the orchestrator can run offline with fake clients."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "multimodel_synthetic_benchmark_orchestrator"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    template_client = _QueuedOpenAIClient(
        [_fake_response({"template": _dynamic_template_payload()})]
    )
    converter_clients = {
        endpoint.name: _QueuedOpenAIClient(
            [
                _fake_response(_static_source_schema()),
                *_fake_mapping_responses(_static_mapping_ir(), module.MAPPING_CANDIDATE_COUNT),
                _fake_response(_dynamic_source_schema()),
                *_fake_mapping_responses(_dynamic_mapping_ir(), module.MAPPING_CANDIDATE_COUNT),
            ]
        )
        for endpoint in module.CONVERTER_MODEL_ENDPOINTS
    }

    summary = module.run_orchestrator(
        output_dir=output_dir,
        benchmark_run_count=1,
        template_generation_client=template_client,
        converter_clients=converter_clients,
    )

    assert len(module.CONVERTER_MODEL_ENDPOINTS) >= 2
    assert len(summary["datasets"]) == 2
    assert len(summary["converter_runs"]) == 2 * len(module.CONVERTER_MODEL_ENDPOINTS)
    assert Path(summary["summary_path"]).exists()

    dataset_by_name = {dataset["dataset_name"]: dataset for dataset in summary["datasets"]}
    assert "static" in dataset_by_name
    assert "llm_dynamic" in dataset_by_name
    assert Path(dataset_by_name["static"]["manifest_path"]).exists()
    assert Path(dataset_by_name["llm_dynamic"]["manifest_path"]).exists()
    assert Path(dataset_by_name["llm_dynamic"]["template_generation_result_path"]).exists()

    for run in summary["converter_runs"]:
        assert Path(run["profile_report_path"]).exists()
        assert Path(run["source_schema_path"]).exists()
        assert Path(run["mapping_ir_path"]).exists()
        assert Path(run["converter_manifest_path"]).exists()
        assert Path(run["benchmark_experiment_json_path"]).exists()
        assert Path(run["benchmark_summary_json_path"]).exists()
        assert run["mapping_validation"]["valid"] is True
        assert run["benchmark_metrics"]["all_scenarios_passed"] is True
        assert run["benchmark_metrics"]["mean_pass_at_1"] == 1.0
        assert run["schema_completion_report"]["field_count_after"] >= run["schema_completion_report"]["field_count_before"]
        assert run["schema_coverage_report"]["missing_required_semantics"] == []
        assert run["mapping_preflight_report"]["missing_required_targets"] == []


def test_orchestrator_completes_omitted_schema_fields_and_reports_preflight() -> None:
    """Verify live-like omitted source schemas are completed before mapping."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "multimodel_schema_completion"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    template_client = _QueuedOpenAIClient(
        [_fake_response({"template": _dynamic_template_payload()})]
    )
    converter_clients = {
        endpoint.name: _QueuedOpenAIClient(
            [
                _fake_response(_incomplete_static_source_schema()),
                *_fake_mapping_responses(_static_mapping_ir(), module.MAPPING_CANDIDATE_COUNT),
                _fake_response(_incomplete_dynamic_source_schema()),
                *_fake_mapping_responses(_dynamic_mapping_ir(), module.MAPPING_CANDIDATE_COUNT),
            ]
        )
        for endpoint in module.CONVERTER_MODEL_ENDPOINTS
    }

    summary = module.run_orchestrator(
        output_dir=output_dir,
        benchmark_run_count=1,
        template_generation_client=template_client,
        converter_clients=converter_clients,
    )

    run_by_dataset = {
        (run["dataset_name"], run["model_name"]): run
        for run in summary["converter_runs"]
    }
    first_static_run = run_by_dataset[("static", module.CONVERTER_MODEL_ENDPOINTS[0].name)]
    first_dynamic_run = run_by_dataset[("llm_dynamic", module.CONVERTER_MODEL_ENDPOINTS[0].name)]

    assert {"status_text", "status_text_label", "duration_days", "assignee", "tags"}.issubset(
        set(first_static_run["schema_completion_report"]["added_paths"])
    )
    assert {"task.days", "task.owner", "task.labels"}.issubset(
        set(first_dynamic_run["schema_completion_report"]["added_paths"])
    )

    for run in summary["converter_runs"]:
        assert run["schema_completion_report"]["field_count_after"] > run["schema_completion_report"]["field_count_before"]
        assert run["schema_coverage_report"]["missing_required_semantics"] == []
        assert run["mapping_preflight_report"]["missing_required_targets"] == []
        assert run["benchmark_metrics"]["all_scenarios_passed"] is True

    first_client = converter_clients[module.CONVERTER_MODEL_ENDPOINTS[0].name]
    mapping_prompts = [
        call["input"][1]["content"]
        for call in first_client.responses.create_calls
        if call.get("metadata", {}).get("stage") == "mapping"
    ]
    assert any("Observed source path hints" in prompt for prompt in mapping_prompts)
    assert any("status_text_label" in prompt for prompt in mapping_prompts)
    for call in first_client.responses.create_calls:
        for value in (call.get("metadata") or {}).values():
            assert len(str(value)) <= 512


def test_repair_mapping_candidate_recovers_copy_prefixed_assignment_refs() -> None:
    """Verify that repair recovers assignment refs like ``copy_task_id``."""

    module = _load_example_module()
    program = MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status_text", dtype="str"),
            SourceReference(id="src_duration", path="duration_days", dtype="int"),
            SourceReference(id="src_tags", path="tags", dtype="list", cardinality="many"),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="id"),
            TargetAssignment(step_id="copy_task_name", target_path="name"),
            TargetAssignment(step_id="copy_status", target_path="status"),
            TargetAssignment(step_id="copy_duration_days", target_path="duration_days"),
            TargetAssignment(step_id="copy_tags", target_path="tags"),
        ],
    )

    repaired_program, repair_report = module._repair_mapping_candidate(
        program,
        source_schema=_static_source_schema(),
    )
    validation = MappingIRValidator().validate(
        repaired_program,
        source_schema=_static_source_schema(),
        target_schema=build_target_schema_card(module.SyntheticBenchmarkTask),
    )

    assert repair_report["repair_applied"] is True
    assert validation.valid is True
    assert any(step["id"].startswith("auto_copy_") for step in repair_report["added_steps"])


def test_repair_mapping_candidate_infers_cast_source_ref_and_default_step() -> None:
    """Verify that repair infers missing cast sources and synthesizes ``default_*`` steps."""

    module = _load_example_module()
    program = MappingIR(
        source_refs=[
            SourceReference(id="src_duration", path="duration_days", dtype="int"),
            SourceReference(id="src_assignee", path="assignee", dtype="str"),
        ],
        steps=[
            MappingStep(
                id="cast_duration_days_int",
                operation=StepOperation(kind="cast", to_type="int"),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="cast_duration_days_int", target_path="duration_days"),
            TargetAssignment(step_id="default_assignee", target_path="assignee"),
        ],
    )

    repaired_program, repair_report = module._repair_mapping_candidate(
        program,
        source_schema=_static_source_schema(),
    )
    validation = MappingIRValidator().validate(
        repaired_program,
        source_schema=_static_source_schema(),
        target_schema=build_target_schema_card(module.SyntheticBenchmarkTask),
    )

    cast_step = next(step for step in repaired_program.steps if step.id == "cast_duration_days_int")
    default_step = next(step for step in repaired_program.steps if step.id == "default_assignee")

    assert repair_report["repair_applied"] is True
    assert validation.valid is True
    assert cast_step.operation.source_ref == "src_duration"
    assert default_step.operation.kind == "default"
    assert default_step.operation.source_ref == "src_assignee"
    assert default_step.operation.value is None


def _load_example_module() -> ModuleType:
    """Load the example script as an importable Python module.

    Returns:
        Loaded module for the example script.
    """

    spec = importlib.util.spec_from_file_location(
        "multimodel_synthetic_benchmark_orchestrator",
        EXAMPLE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the multi-model benchmark orchestrator example.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_response(parsed_payload: Any) -> _FakeOpenAIResponse:
    """Build one deterministic fake OpenAI response.

    Args:
        parsed_payload: Parsed payload returned by the fake response.

    Returns:
        Fake OpenAI response mirroring the payload as JSON text.
    """

    payload = (
        parsed_payload.model_dump(mode="json")
        if hasattr(parsed_payload, "model_dump")
        else parsed_payload
    )
    return _FakeOpenAIResponse(
        output_text=json.dumps(payload, sort_keys=True),
        output_parsed=parsed_payload,
    )


def _fake_mapping_responses(mapping_ir: MappingIR, count: int) -> list[_FakeOpenAIResponse]:
    """Build repeated fake mapping responses for multi-candidate synthesis."""

    return [_fake_response(mapping_ir) for _ in range(count)]


def _dynamic_template_payload() -> dict[str, Any]:
    """Build the accepted LLM template used by the offline orchestration test.

    Returns:
        Template payload accepted by ``TemplateGenerationCandidate``.
    """

    return {
        "version": "1.0",
        "template_id": "llm_wrapped_template",
        "root_mode": "object",
        "records_key": "items",
        "wrap_task_object": True,
        "task_object_key": "task",
        "field_aliases": {
            "entity_id": "task_id",
            "name": "title",
            "status": "state",
            "duration_days": "days",
            "assignee": "owner",
            "tags": "labels",
        },
        "optional_fields": ["assignee", "tags"],
        "extra_fields": {"source": "llm"},
    }


def _static_source_schema() -> SourceSchemaSpec:
    """Build the fake source schema for the static synthetic dataset.

    Returns:
        Source schema payload for static task rows including drifts.
    """

    return SourceSchemaSpec(
        source_name="synthetic_task_rows.json",
        source_format="json",
        root_type="rows",
        fields=[
            SourceFieldSpec(path="task_id", semantic_name="id", dtype="str"),
            SourceFieldSpec(path="task_name", semantic_name="name", dtype="str"),
            SourceFieldSpec(path="status_text", semantic_name="status", dtype="str"),
            SourceFieldSpec(path="status_text_label", semantic_name="status_label", dtype="str"),
            SourceFieldSpec(path="status.details", semantic_name="status_nested", dtype="str"),
            SourceFieldSpec(path="duration_days", semantic_name="duration_days", dtype="int"),
            SourceFieldSpec(path="assignee", semantic_name="assignee", dtype="str"),
            SourceFieldSpec(path="tags", semantic_name="tags", dtype="list", cardinality="many"),
        ],
    )


def _incomplete_static_source_schema() -> SourceSchemaSpec:
    """Build a live-like static schema that omitted profiled fields."""

    return SourceSchemaSpec(
        source_name="synthetic_task_rows.json",
        source_format="json",
        root_type="rows",
        fields=[
            SourceFieldSpec(path="task_id", semantic_name="id", dtype="str"),
            SourceFieldSpec(path="task_name", semantic_name="name", dtype="str"),
            SourceFieldSpec(path="status.details", semantic_name="status_nested", dtype="str"),
            SourceFieldSpec(path="tags[]", semantic_name="tags_item", dtype="str", cardinality="many"),
        ],
    )


def _dynamic_source_schema() -> SourceSchemaSpec:
    """Build the fake source schema for the LLM-driven synthetic dataset.

    Returns:
        Source schema payload for wrapped task rows including drifts.
    """

    return SourceSchemaSpec(
        source_name="synthetic_task_rows.json",
        source_format="json",
        root_type="rows",
        fields=[
            SourceFieldSpec(path="task.task_id", semantic_name="id", dtype="str"),
            SourceFieldSpec(path="task.title", semantic_name="name", dtype="str"),
            SourceFieldSpec(path="task.state", semantic_name="status", dtype="str"),
            SourceFieldSpec(path="task.state_label", semantic_name="status_label", dtype="str"),
            SourceFieldSpec(path="task.status.details", semantic_name="status_nested", dtype="str"),
            SourceFieldSpec(path="task.days", semantic_name="duration_days", dtype="int"),
            SourceFieldSpec(path="task.owner", semantic_name="assignee", dtype="str"),
            SourceFieldSpec(path="task.labels", semantic_name="tags", dtype="list", cardinality="many"),
        ],
    )


def _incomplete_dynamic_source_schema() -> SourceSchemaSpec:
    """Build a live-like dynamic schema that omitted profiled wrapped fields."""

    return SourceSchemaSpec(
        source_name="synthetic_task_rows.json",
        source_format="json",
        root_type="rows",
        fields=[
            SourceFieldSpec(path="task.task_id", semantic_name="id", dtype="str"),
            SourceFieldSpec(path="task.title", semantic_name="name", dtype="str"),
            SourceFieldSpec(path="task.state", semantic_name="status", dtype="str"),
            SourceFieldSpec(path="task.labels[]", semantic_name="tags_item", dtype="str", cardinality="many"),
        ],
    )


def _static_mapping_ir() -> MappingIR:
    """Build a deterministic mapping IR for static synthetic task rows.

    Returns:
        MappingIR that handles baseline, rename, and nesting status surfaces.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status_text", dtype="str"),
            SourceReference(id="src_status_label", path="status_text_label", dtype="str"),
            SourceReference(id="src_status_nested", path="status.details", dtype="str"),
            SourceReference(id="src_duration", path="duration_days", dtype="int"),
            SourceReference(id="src_assignee", path="assignee", dtype="str"),
            SourceReference(id="src_tags", path="tags", dtype="list", cardinality="many"),
        ],
        steps=[
            MappingStep(id="copy_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(
                id="derive_status",
                operation=StepOperation(
                    kind="derive",
                    source_refs=["src_status", "src_status_label", "src_status_nested"],
                    expression=(
                        "src_status if src_status != None "
                        "else (src_status_label if src_status_label != None else src_status_nested)"
                    ),
                ),
            ),
            MappingStep(id="copy_duration", operation=StepOperation(kind="copy", source_ref="src_duration")),
            MappingStep(id="copy_assignee", operation=StepOperation(kind="copy", source_ref="src_assignee")),
            MappingStep(
                id="default_tags",
                operation=StepOperation(kind="default", source_ref="src_tags", value=[]),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_id", target_path="id"),
            TargetAssignment(step_id="copy_name", target_path="name"),
            TargetAssignment(step_id="derive_status", target_path="status"),
            TargetAssignment(step_id="copy_duration", target_path="duration_days"),
            TargetAssignment(step_id="copy_assignee", target_path="assignee"),
            TargetAssignment(step_id="default_tags", target_path="tags"),
        ],
    )


def _dynamic_mapping_ir() -> MappingIR:
    """Build a deterministic mapping IR for wrapped LLM-driven task rows.

    Returns:
        MappingIR that handles wrapped baseline, rename, and nesting status surfaces.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task.task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task.title", dtype="str"),
            SourceReference(id="src_status", path="task.state", dtype="str"),
            SourceReference(id="src_status_label", path="task.state_label", dtype="str"),
            SourceReference(id="src_status_nested", path="task.status.details", dtype="str"),
            SourceReference(id="src_duration", path="task.days", dtype="int"),
            SourceReference(id="src_assignee", path="task.owner", dtype="str"),
            SourceReference(id="src_tags", path="task.labels", dtype="list", cardinality="many"),
        ],
        steps=[
            MappingStep(id="copy_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(
                id="derive_status",
                operation=StepOperation(
                    kind="derive",
                    source_refs=["src_status", "src_status_label", "src_status_nested"],
                    expression=(
                        "src_status if src_status != None "
                        "else (src_status_label if src_status_label != None else src_status_nested)"
                    ),
                ),
            ),
            MappingStep(id="copy_duration", operation=StepOperation(kind="copy", source_ref="src_duration")),
            MappingStep(id="copy_assignee", operation=StepOperation(kind="copy", source_ref="src_assignee")),
            MappingStep(
                id="default_tags",
                operation=StepOperation(kind="default", source_ref="src_tags", value=[]),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="copy_id", target_path="id"),
            TargetAssignment(step_id="copy_name", target_path="name"),
            TargetAssignment(step_id="derive_status", target_path="status"),
            TargetAssignment(step_id="copy_duration", target_path="duration_days"),
            TargetAssignment(step_id="copy_assignee", target_path="assignee"),
            TargetAssignment(step_id="default_tags", target_path="tags"),
        ],
    )
