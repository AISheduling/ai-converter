"""Smoke test for the from-scratch example pipeline."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ai_converter.mapping_ir import MappingIR, MappingStep, SourceReference, StepOperation, TargetAssignment
from ai_converter.schema import SourceFieldSpec, SourceSchemaSpec

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SCRIPT = ROOT / "examples" / "from_scratch_pipeline" / "run_example.py"


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


class _FakeResponsesAPI:
    """Queued fake ``responses`` namespace for offline example tests."""

    def __init__(self, responses: list[_FakeOpenAIResponse]) -> None:
        """Store the queued parse responses.

        Args:
            responses: Ordered fake responses for schema and mapping synthesis.

        Returns:
            None.
        """

        self._responses = list(responses)
        self.create_calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        """Return the next queued create response."""

        self.create_calls.append(kwargs)
        return self._responses.pop(0)

    def parse(self, **kwargs: Any) -> _FakeOpenAIResponse:
        """Return the next queued parse response.

        Args:
            **kwargs: Request payload captured for assertions when needed.

        Returns:
            The next fake OpenAI response.
        """

        self.parse_calls.append(kwargs)
        return self._responses.pop(0)


class _FailingResponsesAPI(_FakeResponsesAPI):
    """Fake ``responses`` namespace that fails on a chosen parse call."""

    def __init__(self, responses: list[_FakeOpenAIResponse], *, failure_call: int, message: str) -> None:
        """Store queued responses plus one deterministic failing call."""

        super().__init__(responses)
        self._failure_call = failure_call
        self._message = message

    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        """Raise a deterministic error on the configured create call."""

        self.create_calls.append(kwargs)
        format_payload = kwargs.get("text", {}).get("format", {})
        if len(self.create_calls) == self._failure_call and format_payload.get("type") == "json_schema":
            raise RuntimeError(self._message)
        return self._responses.pop(0)


class _FakeOpenAIClient:
    """Fake OpenAI-like client injected into the example script."""

    def __init__(self) -> None:
        """Build the fake client with deterministic schema and mapping replies."""

        self.responses = _FakeResponsesAPI(
            [
                _FakeOpenAIResponse(
                    output_text=json.dumps(_source_schema().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_source_schema(),
                ),
                _FakeOpenAIResponse(
                    output_text=json.dumps(_mapping_ir().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_mapping_ir(),
                ),
            ]
        )


class _SchemaRejectingOpenAIClient:
    """Fake OpenAI-like client that would reject strict JSON Schema once."""

    def __init__(self) -> None:
        """Return valid responses while rejecting the strict mapping schema if sent."""

        self.responses = _FailingResponsesAPI(
            [
                _FakeOpenAIResponse(
                    output_text=json.dumps(_source_schema().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_source_schema(),
                ),
                _FakeOpenAIResponse(
                    output_text=json.dumps(_mapping_ir().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_mapping_ir(),
                ),
            ],
            failure_call=2,
            message=(
                "Error code: 400 - {'error': {'message': "
                "\"Invalid schema for response_format 'MappingIR': In context=(), "
                "'required' is required to be supplied and to be an array including every key in properties. "
                "Extra required key 'child_keys' supplied.\", 'code': 'invalid_json_schema'}}"
            ),
        )


class _RecoverableInvalidMappingOpenAIClient:
    """Fake client that returns a parseable but semantically sloppy MappingIR."""

    def __init__(self) -> None:
        """Queue a schema response plus one recoverably invalid mapping candidate."""

        self.responses = _FakeResponsesAPI(
            [
                _FakeOpenAIResponse(
                    output_text=json.dumps(_source_schema().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_source_schema(),
                ),
                _FakeOpenAIResponse(
                    output_text=json.dumps(_recoverable_invalid_mapping_ir().model_dump(mode="json"), sort_keys=True),
                    output_parsed=_recoverable_invalid_mapping_ir(),
                ),
            ]
        )


def test_from_scratch_pipeline_example_runs_offline() -> None:
    """Verify that the from-scratch example stays runnable offline."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "from_scratch_pipeline_example"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    summary = module.run_example(output_dir=output_dir, client=_FakeOpenAIClient())
    baseline_sample = json.loads(
        (ROOT / "examples" / "from_scratch_pipeline" / "source_samples" / "sample_01.json").read_text(encoding="utf-8")
    )
    drift_sample = json.loads(
        (ROOT / "examples" / "from_scratch_pipeline" / "drift_samples" / "rename_candidate_01.json").read_text(encoding="utf-8")
    )

    assert summary["mapping_candidate_count"] == 1
    assert summary["mapping_repair_applied"] is False
    assert summary["mapping_validation"]["valid"] is True
    assert summary["converted_validation"]["valid"] is True
    assert summary["drift_classification"] == "rename_compatible"
    assert summary["drift_compatible"] is True
    assert summary["drift_resolution_compatible"] is True
    assert summary["drift_patch_applied"] is True
    assert summary["budget_accounting"]["total_used"] == 2
    assert Path(summary["converter_manifest_path"]).exists()
    assert Path(summary["converted_payload_path"]).exists()
    assert Path(summary["drift_report_path"]).exists()
    assert Path(summary["patched_source_schema_path"]).exists()
    assert Path(summary["patched_mapping_ir_path"]).exists()
    assert isinstance(baseline_sample["subtasks"], list)
    assert isinstance(baseline_sample["subtasks"][0], dict)
    assert isinstance(baseline_sample["subtasks"][0]["notes"], list)
    assert isinstance(baseline_sample["milestones"], list)
    assert isinstance(baseline_sample["milestones"][0]["owners"], list)
    assert isinstance(drift_sample["subtasks"][0]["notes"][0], dict)

    converted_payload = json.loads(Path(summary["converted_payload_path"]).read_text(encoding="utf-8"))
    drift_report = json.loads(Path(summary["drift_report_path"]).read_text(encoding="utf-8"))
    drift_resolution = json.loads(Path(summary["drift_resolution_path"]).read_text(encoding="utf-8"))
    patched_mapping_ir = json.loads(Path(summary["patched_mapping_ir_path"]).read_text(encoding="utf-8"))

    assert converted_payload == {
        "owner": "dana",
        "task": {
            "id": "TASK-200",
            "name": "Ship example docs",
            "status": "ready",
        },
    }
    assert drift_report["classification"] == "rename_compatible"
    assert any(
        field_drift["kind"] == "renamed"
        and field_drift["baseline_path"] == "task_name"
        and field_drift["candidate_path"] == "taskName"
        for field_drift in drift_report["field_drifts"]
    )
    assert any(
        decision["kind"] == "rename_alignment"
        for decision in drift_resolution["decisions"]
    )
    assert any(
        source_ref["id"] == "src_task_name" and source_ref["path"] == "taskName"
        for source_ref in patched_mapping_ir["source_refs"]
    )


def test_from_scratch_pipeline_example_uses_proactive_json_mode_for_mapping_ir_proxy_compatibility() -> None:
    """Verify that the example skips the known-incompatible strict mapping schema mode."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "from_scratch_pipeline_example_failure"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    summary = module.run_example(output_dir=output_dir, client=_SchemaRejectingOpenAIClient())
    trace = json.loads((output_dir / "mapping_candidate_0.trace.json").read_text(encoding="utf-8"))

    assert summary["mapping_validation"]["valid"] is True
    assert summary["converted_validation"]["valid"] is True
    assert trace["metadata"]["structured_output_mode"] == "json_object_proactive"
    assert "proxy_compatibility" in trace["metadata"]["structured_output_fallback_reason"]


def test_from_scratch_pipeline_example_repairs_recoverable_mapping_references() -> None:
    """Verify that the example repairs narrow reference-shape mistakes locally."""

    module = _load_example_module()
    output_dir = ROOT / ".pytest-local-tmp" / "from_scratch_pipeline_example_repair"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    summary = module.run_example(output_dir=output_dir, client=_RecoverableInvalidMappingOpenAIClient())
    selection = json.loads((output_dir / "mapping_selection.json").read_text(encoding="utf-8"))
    mapping_ir = json.loads((output_dir / "mapping_ir.json").read_text(encoding="utf-8"))
    converted_payload = json.loads((output_dir / "converted_payload.json").read_text(encoding="utf-8"))

    assert summary["mapping_repair_applied"] is True
    assert summary["mapping_validation"]["valid"] is True
    assert summary["converted_validation"]["valid"] is True
    assert selection["selection_mode"] == "repaired_candidate"
    assert selection["repair_report"]["repair_applied"] is True
    assert any(
        rewrite["location"] == "steps.task_obj.operation.step_refs[0]"
        and rewrite["before"] == "task_id"
        and rewrite["after"] == "auto_copy_src_task_id"
        for rewrite in selection["repair_report"]["rewritten_references"]
    )
    assert any(
        rewrite["location"] == "assignments.owner"
        and rewrite["before"] == "owner"
        and rewrite["after"] == "auto_copy_src_owner"
        for rewrite in selection["repair_report"]["rewritten_references"]
    )
    assert any(
        rewrite["location"] == "postconditions.task"
        and rewrite["before"] == "task"
        and rewrite["after"] == "task_obj"
        for rewrite in selection["repair_report"]["rewritten_references"]
    )
    assert any(step["id"] == "auto_copy_src_task_id" for step in mapping_ir["steps"])
    assert any(step["id"] == "auto_copy_src_owner" for step in mapping_ir["steps"])
    assert converted_payload == {
        "owner": "dana",
        "task": {
            "id": "TASK-200",
            "name": "Ship example docs",
            "status": "ready",
        },
    }


def _load_example_module() -> ModuleType:
    """Load the example script as an importable Python module.

    Returns:
        Loaded module for the example script.
    """

    spec = importlib.util.spec_from_file_location("from_scratch_pipeline_example", EXAMPLE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the from-scratch example module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _source_schema() -> SourceSchemaSpec:
    """Build the deterministic source schema returned by the fake client.

    Returns:
        Source schema payload for the example baseline data.
    """

    return SourceSchemaSpec(
        source_name="combined_baseline.json",
        source_format="json",
        root_type="list",
        fields=[
            SourceFieldSpec(path="owner", semantic_name="owner", dtype="str"),
            SourceFieldSpec(path="status", semantic_name="status", dtype="str"),
            SourceFieldSpec(path="task_id", semantic_name="task_id", dtype="str"),
            SourceFieldSpec(path="task_name", semantic_name="task_name", dtype="str"),
        ],
    )


def _mapping_ir() -> MappingIR:
    """Build the deterministic MappingIR program returned by the fake client.

    Returns:
        MappingIR payload that populates the example target model.
    """

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status", dtype="str"),
            SourceReference(id="src_owner", path="owner", dtype="str"),
        ],
        steps=[
            MappingStep(id="copy_task_id", operation=StepOperation(kind="copy", source_ref="src_task_id")),
            MappingStep(id="copy_task_name", operation=StepOperation(kind="copy", source_ref="src_task_name")),
            MappingStep(id="copy_status", operation=StepOperation(kind="copy", source_ref="src_status")),
            MappingStep(id="copy_owner", operation=StepOperation(kind="copy", source_ref="src_owner")),
        ],
        assignments=[
            TargetAssignment(step_id="copy_task_id", target_path="task.id"),
            TargetAssignment(step_id="copy_task_name", target_path="task.name"),
            TargetAssignment(step_id="copy_status", target_path="task.status"),
            TargetAssignment(step_id="copy_owner", target_path="owner"),
        ],
    )


def _recoverable_invalid_mapping_ir() -> MappingIR:
    """Build a MappingIR candidate with recoverable step/reference mistakes."""

    return MappingIR(
        source_refs=[
            SourceReference(id="src_task_id", path="task_id", dtype="str"),
            SourceReference(id="src_task_name", path="task_name", dtype="str"),
            SourceReference(id="src_status", path="status", dtype="str"),
            SourceReference(id="src_owner", path="owner", dtype="str"),
        ],
        steps=[
            MappingStep(
                id="task_obj",
                operation=StepOperation(
                    kind="nest",
                    step_refs=["task_id", "task_name", "status"],
                    child_keys={
                        "task_id": "id",
                        "task_name": "name",
                        "status": "status",
                    },
                ),
            ),
        ],
        assignments=[
            TargetAssignment(step_id="task_obj", target_path="task"),
            TargetAssignment(step_id="owner", target_path="owner"),
        ],
        postconditions=[
            {
                "kind": "non_null",
                "ref": "task",
                "description": "The assembled task object should be present.",
            }
        ],
    )
