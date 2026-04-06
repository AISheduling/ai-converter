"""From-scratch end-to-end converter pipeline example."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ai_converter.compiler import compile_mapping_ir
from ai_converter.drift import apply_converter_patch, classify_drift, propose_compatible_patch
from ai_converter.llm import LLMCallBudgetPolicy, OpenAILLMAdapter
from ai_converter.mapping_ir import (
    ConditionClause,
    MappingIR,
    MappingIRValidator,
    MappingStep,
    MappingSynthesizer,
    SourceReference,
    StepOperation,
    TargetAssignment,
)
from ai_converter.profiling import build_profile_report
from ai_converter.schema import (
    SourceSchemaSpec,
    TargetSchemaCard,
    build_target_schema_card,
    normalize_source_schema_spec,
)
from ai_converter.validation import validate_structural_output

EXAMPLE_ROOT = Path(__file__).resolve().parent
BASELINE_SAMPLE_DIR = EXAMPLE_ROOT / "source_samples"
DRIFT_SAMPLE_DIR = EXAMPLE_ROOT / "drift_samples"
CONVERT_RECORD_PATH = EXAMPLE_ROOT / "convert_record.json"
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "generated"

OPENAI_BASE_URL = "https://api.duckduck.cloud/v1"
OPENAI_API_TOKEN = "sk-SYfxVvd0UuqoYdZQsUaVaA"
OPENAI_MODEL = "gpt-5.4-mini"

SCHEMA_BUDGET = 1800
MAPPING_CANDIDATE_COUNT = 1


class ExampleTask(BaseModel):
    """Nested target task produced by the compiled converter."""

    id: str = Field(description="Stable task identifier.")
    name: str = Field(description="Human-readable task name.")
    status: str = Field(description="Current workflow status.")


class ExampleTargetRecord(BaseModel):
    """Root target payload used by the from-scratch example."""

    task: ExampleTask = Field(description="Nested task payload.")
    owner: str = Field(description="Primary task owner.")


def run_example(
    *,
    output_dir: str | Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the full example pipeline and persist its artifacts.

    Args:
        output_dir: Optional destination for generated example artifacts.
        client: Optional injected OpenAI-compatible client for offline tests.

    Returns:
        Summary of the generated artifacts and key pipeline results.
    """

    output_root = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    if client is None and OPENAI_API_TOKEN.startswith("replace-"):
        raise RuntimeError(
            "Set OPENAI_API_TOKEN in examples/from_scratch_pipeline/run_example.py "
            "before running the live OpenAI-backed example."
        )

    baseline_bundle_path = _combine_json_objects(
        sorted(BASELINE_SAMPLE_DIR.glob("*.json")),
        output_root / "combined_baseline.json",
    )
    baseline_report = build_profile_report(baseline_bundle_path, sample_limit=3)
    _write_json(output_root / "baseline_profile.json", baseline_report.model_dump(mode="json"))

    target_schema = build_target_schema_card(ExampleTargetRecord)
    _write_json(output_root / "target_schema_card.json", target_schema.model_dump(mode="json"))

    synthesizer = MappingSynthesizer(
        OpenAILLMAdapter(
            model=OPENAI_MODEL,
            api_key=OPENAI_API_TOKEN,
            base_url=OPENAI_BASE_URL,
            client=client,
        ),
        budget_policy=LLMCallBudgetPolicy(schema=1, mapping=MAPPING_CANDIDATE_COUNT, repair=0),
    )

    schema_response = synthesizer.synthesize_source_schema(
        baseline_report,
        budget=SCHEMA_BUDGET,
        mode="balanced",
        format_hint="flat task schedule json examples",
        metadata={"example": "from_scratch_pipeline", "stage": "schema"},
    )
    source_schema = _require_parsed(schema_response, label="source schema")
    source_schema = normalize_source_schema_spec(source_schema)
    if source_schema.schema_fingerprint is None:
        source_schema = source_schema.model_copy(
            update={"schema_fingerprint": baseline_report.schema_fingerprint}
        )
    _write_json(
        output_root / "llm_source_schema_trace.json",
        schema_response.to_trace_artifact(),
    )
    _write_json(output_root / "source_schema.json", source_schema.model_dump(mode="json"))

    mapping_result = synthesizer.synthesize_mapping(
        source_schema,
        target_schema,
        candidate_count=MAPPING_CANDIDATE_COUNT,
        conversion_hint=(
            "Map the flat source fields task_id, task_name, status, and owner "
            "into the nested ExampleTargetRecord target."
        ),
        metadata={"example": "from_scratch_pipeline", "stage": "mapping"},
    )
    for candidate in mapping_result.candidates:
        _write_json(
            output_root / f"mapping_candidate_{candidate.index}.trace.json",
            candidate.response.to_trace_artifact(),
        )

    mapping_ir, mapping_selection = _select_mapping_candidate(
        mapping_result,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    _write_json(output_root / "mapping_selection.json", mapping_selection)
    mapping_validation = MappingIRValidator().validate(
        mapping_ir,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    if not mapping_validation.valid:
        raise RuntimeError(
            "Synthesized MappingIR did not validate: "
            + "; ".join(
                f"{issue.location}: {issue.message}" for issue in mapping_validation.issues
            )
        )
    _write_json(
        output_root / "mapping_validation.json",
        mapping_validation.model_dump(mode="json"),
    )
    _write_json(output_root / "mapping_ir.json", mapping_ir.model_dump(mode="json"))

    package = compile_mapping_ir(mapping_ir, module_name="from_scratch_converter")
    export = package.export(output_root / "converter_package")

    convert_record = _load_json_payload(CONVERT_RECORD_PATH)
    if not isinstance(convert_record, dict):
        raise ValueError("convert_record.json must contain one JSON object")
    converted_payload = package.convert(convert_record)
    structural_validation = validate_structural_output(
        converted_payload,
        ExampleTargetRecord,
    )
    if not structural_validation.valid:
        raise RuntimeError("Converted payload did not satisfy the ExampleTargetRecord contract.")
    _write_json(output_root / "converted_payload.json", converted_payload)
    _write_json(
        output_root / "structural_validation.json",
        structural_validation.model_dump(mode="json"),
    )

    drift_bundle_path = _combine_json_objects(
        sorted(DRIFT_SAMPLE_DIR.glob("*.json")),
        output_root / "combined_drift_candidate.json",
    )
    drift_profile = build_profile_report(drift_bundle_path, sample_limit=3)
    drift_report = classify_drift(
        baseline_report,
        drift_profile,
        baseline_schema=source_schema,
    )
    drift_resolution = propose_compatible_patch(drift_report, source_schema, mapping_ir)
    patched_source_schema_path: str | None = None
    patched_mapping_ir_path: str | None = None
    _write_json(output_root / "drift_profile.json", drift_profile.model_dump(mode="json"))
    _write_json(output_root / "drift_report.json", drift_report.model_dump(mode="json"))
    _write_json(
        output_root / "drift_resolution.json",
        drift_resolution.model_dump(mode="json"),
    )
    if drift_resolution.patch is not None:
        _write_json(
            output_root / "drift_patch.json",
            drift_resolution.patch.model_dump(mode="json"),
        )
        patched_source_schema, patched_mapping_ir = apply_converter_patch(
            source_schema,
            mapping_ir,
            drift_resolution.patch,
        )
        _write_json(
            output_root / "patched_source_schema.json",
            patched_source_schema.model_dump(mode="json"),
        )
        _write_json(
            output_root / "patched_mapping_ir.json",
            patched_mapping_ir.model_dump(mode="json"),
        )
        patched_source_schema_path = str(output_root / "patched_source_schema.json")
        patched_mapping_ir_path = str(output_root / "patched_mapping_ir.json")

    budget_accounting = (
        mapping_result.budget_accounting.to_dict()
        if mapping_result.budget_accounting is not None
        else None
    )
    summary = {
        "output_dir": str(output_root),
        "baseline_profile_path": str(output_root / "baseline_profile.json"),
        "source_schema_path": str(output_root / "source_schema.json"),
        "mapping_ir_path": str(output_root / "mapping_ir.json"),
        "mapping_selection_path": str(output_root / "mapping_selection.json"),
        "converter_manifest_path": str(export.manifest_path),
        "converted_payload_path": str(output_root / "converted_payload.json"),
        "drift_report_path": str(output_root / "drift_report.json"),
        "drift_resolution_path": str(output_root / "drift_resolution.json"),
        "patched_source_schema_path": patched_source_schema_path,
        "patched_mapping_ir_path": patched_mapping_ir_path,
        "mapping_candidate_count": len(mapping_result.candidates),
        "selected_mapping_candidate_index": mapping_selection["selected_candidate_index"],
        "mapping_repair_applied": bool(mapping_selection.get("repair_applied")),
        "mapping_repair_action_count": (
            len(mapping_selection.get("repair_report", {}).get("rewritten_references", []))
            + len(mapping_selection.get("repair_report", {}).get("added_source_refs", []))
            + len(mapping_selection.get("repair_report", {}).get("added_steps", []))
        ),
        "mapping_validation": mapping_validation.model_dump(mode="json"),
        "converted_validation": structural_validation.model_dump(mode="json"),
        "drift_classification": drift_report.classification,
        "drift_compatible": drift_report.compatible,
        "drift_resolution_compatible": drift_resolution.compatible,
        "drift_patch_applied": drift_resolution.patch is not None,
        "budget_accounting": budget_accounting,
    }
    _write_json(output_root / "summary.json", summary)
    return summary


def _combine_json_objects(paths: list[Path], destination: Path) -> Path:
    """Merge repo-local JSON object files into one list-shaped JSON document.

    Args:
        paths: Ordered JSON files to load and combine.
        destination: Artifact path that will receive the combined list payload.

    Returns:
        Destination path after the combined payload is written.
    """

    if not paths:
        raise ValueError("At least one JSON input file is required.")

    combined_records: list[dict[str, Any]] = []
    for path in paths:
        payload = _load_json_payload(path)
        if isinstance(payload, dict):
            combined_records.append(payload)
            continue
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            combined_records.extend(payload)
            continue
        raise ValueError(f"Unsupported example JSON payload in {path}: expected object or list[object].")

    _write_json(destination, combined_records)
    return destination


def _load_json_payload(path: Path) -> Any:
    """Load one UTF-8 JSON document from disk.

    Args:
        path: JSON file to load.

    Returns:
        Parsed JSON payload from the file.
    """

    return json.loads(path.read_text(encoding="utf-8"))


def _require_parsed(response: Any, *, label: str) -> Any:
    """Return the parsed adapter payload or raise a helpful error.

    Args:
        response: Adapter response returned by the synthesis layer.
        label: Human-readable label for the expected payload.

    Returns:
        Parsed payload from the response.
    """

    if response.ok and response.parsed is not None:
        return response.parsed

    error_messages = ", ".join(error.message for error in response.errors) or "unknown adapter error"
    raise RuntimeError(f"Failed to generate {label}: {error_messages}")


def _select_mapping_candidate(
    mapping_result: Any,
    *,
    source_schema: SourceSchemaSpec,
    target_schema: TargetSchemaCard,
) -> tuple[MappingIR, dict[str, Any]]:
    """Pick the first valid candidate or repair a recoverable one locally.

    Args:
        mapping_result: Ordered mapping synthesis result returned by the orchestrator.
        source_schema: Canonical source schema available to the example.
        target_schema: Canonical target schema available to the example.

    Returns:
        The selected mapping candidate and a machine-readable selection report.
    """

    for candidate in mapping_result.candidates:
        if candidate.ranked.validation.valid and candidate.ranked.candidate is not None:
            return candidate.ranked.candidate, {
                "selected_candidate_index": candidate.index,
                "selection_mode": "direct_valid_candidate",
                "repair_applied": False,
                "initial_validation": candidate.ranked.validation.model_dump(mode="json"),
            }

    diagnostics: list[str] = []
    for candidate in mapping_result.candidates:
        if candidate.response.parsed is None:
            if candidate.response.errors:
                diagnostics.extend(
                    f"candidate {candidate.index}: {error.message}"
                    for error in candidate.response.errors
                )
            else:
                diagnostics.append(f"candidate {candidate.index}: no parsed mapping candidate was returned")
            continue

        repaired_candidate, repair_report = _repair_mapping_candidate(
            candidate.response.parsed,
            source_schema=source_schema,
        )
        validation = MappingIRValidator().validate(
            repaired_candidate,
            source_schema=source_schema,
            target_schema=target_schema,
        )
        repair_report["post_repair_validation"] = validation.model_dump(mode="json")
        if validation.valid:
            return repaired_candidate, {
                "selected_candidate_index": candidate.index,
                "selection_mode": "repaired_candidate",
                "repair_applied": repair_report["repair_applied"],
                "initial_validation": candidate.ranked.validation.model_dump(mode="json"),
                "repair_report": repair_report,
            }

        diagnostics.extend(
            f"candidate {candidate.index}: {issue.location}: {issue.message}"
            for issue in validation.issues
        )

    detail = "; ".join(diagnostics) if diagnostics else "no mapping candidates were returned"
    raise RuntimeError(f"Mapping synthesis did not produce a valid candidate. Details: {detail}")


def _repair_mapping_candidate(
    program: MappingIR,
    *,
    source_schema: SourceSchemaSpec,
) -> tuple[MappingIR, dict[str, Any]]:
    """Repair narrow live-model reference mistakes without changing IR semantics.

    The repair is intentionally conservative:
    - canonicalize source references back to declared source-ref ids;
    - synthesize explicit copy steps when a source ref is used in a step-only slot;
    - rewrite condition refs that accidentally point at uniquely assigned target paths.

    Args:
        program: Parsed mapping candidate returned by the adapter.
        source_schema: Canonical source schema for this example run.

    Returns:
        The repaired program plus a structured repair report.
    """

    source_refs = list(program.source_refs)
    source_ids = {source_ref.id for source_ref in source_refs}
    source_ref_by_id = {source_ref.id: source_ref for source_ref in source_refs}
    source_ref_by_path = {source_ref.path: source_ref for source_ref in source_refs}
    source_field_by_key: dict[str, Any] = {}
    for field in source_schema.fields:
        for key in [field.path, field.semantic_name, *field.aliases]:
            source_field_by_key.setdefault(key, field)

    rewritten_references: list[dict[str, Any]] = []
    added_source_refs: list[dict[str, Any]] = []
    added_steps: list[dict[str, Any]] = []

    original_steps = list(program.steps)
    existing_step_ids = {step.id for step in original_steps}
    passthrough_step_by_source_ref: dict[str, str] = {}
    appended_steps: list[MappingStep] = []

    def _record_rewrite(*, kind: str, location: str, before: str, after: str) -> None:
        if before == after:
            return
        rewritten_references.append(
            {
                "kind": kind,
                "location": location,
                "before": before,
                "after": after,
            }
        )

    def _ensure_source_ref(token: str, *, location: str) -> str | None:
        normalized = token.strip()
        if not normalized:
            return None
        if normalized in source_ref_by_id:
            return normalized
        if normalized in source_ref_by_path:
            resolved = source_ref_by_path[normalized].id
            _record_rewrite(
                kind="canonicalize_source_ref",
                location=location,
                before=normalized,
                after=resolved,
            )
            return resolved
        field = source_field_by_key.get(normalized)
        if field is None:
            return None
        existing_ref = source_ref_by_path.get(field.path)
        if existing_ref is not None:
            _record_rewrite(
                kind="canonicalize_source_ref",
                location=location,
                before=normalized,
                after=existing_ref.id,
            )
            return existing_ref.id

        new_id = _unique_identifier(f"src_{_slugify_identifier(field.path)}", used=source_ids)
        new_source_ref = SourceReference(
            id=new_id,
            path=field.path,
            dtype=field.dtype,
            cardinality=field.cardinality,
            description=field.description,
        )
        source_refs.append(new_source_ref)
        source_ids.add(new_id)
        source_ref_by_id[new_id] = new_source_ref
        source_ref_by_path[field.path] = new_source_ref
        added_source_refs.append(new_source_ref.model_dump(mode="json"))
        _record_rewrite(
            kind="add_missing_source_ref",
            location=location,
            before=normalized,
            after=new_id,
        )
        return new_id

    def _ensure_passthrough_step(token: str, *, location: str) -> str | None:
        source_ref_id = _ensure_source_ref(token, location=location)
        if source_ref_id is None:
            return None
        existing_step_id = passthrough_step_by_source_ref.get(source_ref_id)
        if existing_step_id is not None:
            _record_rewrite(
                kind="rewrite_step_reference",
                location=location,
                before=token,
                after=existing_step_id,
            )
            return existing_step_id

        step_id = _unique_identifier(
            f"auto_copy_{_slugify_identifier(source_ref_id)}",
            used=existing_step_ids,
        )
        auto_copy_step = MappingStep(
            id=step_id,
            operation=StepOperation(kind="copy", source_ref=source_ref_id),
            description="Auto-generated copy step for a recovered source reference.",
        )
        appended_steps.append(auto_copy_step)
        existing_step_ids.add(step_id)
        passthrough_step_by_source_ref[source_ref_id] = step_id
        added_steps.append(auto_copy_step.model_dump(mode="json"))
        _record_rewrite(
            kind="rewrite_step_reference",
            location=location,
            before=token,
            after=step_id,
        )
        return step_id

    def _resolve_step_reference(token: str, *, location: str) -> str | None:
        normalized = token.strip()
        if not normalized:
            return None
        if normalized in existing_step_ids:
            return normalized
        return _ensure_passthrough_step(normalized, location=location)

    for step in original_steps:
        if (
            step.operation.kind in {"copy", "rename"}
            and step.operation.source_ref is not None
            and not step.operation.source_refs
            and not step.operation.step_refs
            and not step.depends_on
        ):
            canonical_source_ref = (
                _ensure_source_ref(
                    step.operation.source_ref,
                    location=f"steps.{step.id}.operation.source_ref",
                )
                or step.operation.source_ref
            )
            passthrough_step_by_source_ref.setdefault(canonical_source_ref, step.id)

    rewritten_steps: list[MappingStep] = []
    for step in original_steps:
        resolved_source_ref = step.operation.source_ref
        if resolved_source_ref is not None:
            resolved_source_ref = (
                _ensure_source_ref(
                    resolved_source_ref,
                    location=f"steps.{step.id}.operation.source_ref",
                )
                or resolved_source_ref
            )

        resolved_source_refs: list[str] = []
        for index, source_ref in enumerate(step.operation.source_refs):
            resolved_source_refs.append(
                _ensure_source_ref(
                    source_ref,
                    location=f"steps.{step.id}.operation.source_refs[{index}]",
                )
                or source_ref
            )

        resolved_step_refs: list[str] = []
        original_to_resolved_step_ref: dict[str, str] = {}
        for index, step_ref in enumerate(step.operation.step_refs):
            resolved_step_ref = (
                _resolve_step_reference(
                    step_ref,
                    location=f"steps.{step.id}.operation.step_refs[{index}]",
                )
                or step_ref
            )
            resolved_step_refs.append(resolved_step_ref)
            original_to_resolved_step_ref[step_ref] = resolved_step_ref

        resolved_child_keys: dict[str, str] = {}
        for child_ref, child_key in step.operation.child_keys.items():
            resolved_child_ref = original_to_resolved_step_ref.get(child_ref)
            if resolved_child_ref is None:
                resolved_child_ref = (
                    _resolve_step_reference(
                        child_ref,
                        location=f"steps.{step.id}.operation.child_keys[{child_ref}]",
                    )
                    or child_ref
                )
            if resolved_child_ref in resolved_step_refs:
                resolved_child_keys[resolved_child_ref] = child_key

        resolved_depends_on: list[str] = []
        for index, dependency in enumerate(step.depends_on):
            resolved_depends_on.append(
                _resolve_step_reference(
                    dependency,
                    location=f"steps.{step.id}.depends_on[{index}]",
                )
                or dependency
            )

        rewritten_steps.append(
            step.model_copy(
                update={
                    "operation": step.operation.model_copy(
                        update={
                            "source_ref": resolved_source_ref,
                            "source_refs": _dedupe_preserve_order(resolved_source_refs),
                            "step_refs": _dedupe_preserve_order(resolved_step_refs),
                            "child_keys": resolved_child_keys,
                        }
                    ),
                    "depends_on": _dedupe_preserve_order(resolved_depends_on),
                }
            )
        )

    rewritten_assignments: list[TargetAssignment] = []
    for assignment in program.assignments:
        resolved_step_id = assignment.step_id
        if resolved_step_id not in existing_step_ids:
            resolved_step_id = (
                _resolve_step_reference(
                    assignment.step_id,
                    location=f"assignments.{assignment.target_path}",
                )
                or assignment.step_id
            )
        rewritten_assignments.append(
            assignment.model_copy(update={"step_id": resolved_step_id})
        )

    target_path_counts: dict[str, int] = {}
    for assignment in rewritten_assignments:
        target_path_counts[assignment.target_path] = target_path_counts.get(assignment.target_path, 0) + 1
    assignment_step_by_target_path = {
        assignment.target_path: assignment.step_id
        for assignment in rewritten_assignments
        if target_path_counts[assignment.target_path] == 1
    }

    def _resolve_condition_reference(condition: ConditionClause, *, location: str) -> str | None:
        normalized = condition.ref.strip()
        if not normalized:
            return None
        if normalized in existing_step_ids or normalized in source_ids:
            return normalized
        if normalized in assignment_step_by_target_path:
            resolved = assignment_step_by_target_path[normalized]
            _record_rewrite(
                kind="rewrite_condition_reference",
                location=location,
                before=normalized,
                after=resolved,
            )
            return resolved
        return _ensure_source_ref(normalized, location=location)

    rewritten_preconditions = [
        condition.model_copy(
            update={
                "ref": _resolve_condition_reference(
                    condition,
                    location=f"preconditions.{condition.ref}",
                )
                or condition.ref
            }
        )
        for condition in program.preconditions
    ]
    rewritten_postconditions = [
        condition.model_copy(
            update={
                "ref": _resolve_condition_reference(
                    condition,
                    location=f"postconditions.{condition.ref}",
                )
                or condition.ref
            }
        )
        for condition in program.postconditions
    ]

    repaired_program = program.model_copy(
        update={
            "source_refs": source_refs,
            "steps": rewritten_steps + appended_steps,
            "assignments": rewritten_assignments,
            "preconditions": rewritten_preconditions,
            "postconditions": rewritten_postconditions,
        }
    )
    repair_report = {
        "repair_applied": bool(rewritten_references or added_source_refs or added_steps),
        "rewritten_references": rewritten_references,
        "added_source_refs": added_source_refs,
        "added_steps": added_steps,
    }
    return repaired_program, repair_report


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return values without duplicates while preserving first occurrence order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _slugify_identifier(value: str) -> str:
    """Return a deterministic identifier slug safe for generated ids."""

    collapsed = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return collapsed or "value"


def _unique_identifier(base: str, *, used: set[str]) -> str:
    """Return a unique identifier by appending a numeric suffix when needed."""

    if base not in used:
        return base
    suffix = 2
    while f"{base}_{suffix}" in used:
        suffix += 1
    return f"{base}_{suffix}"


def _write_json(path: Path, payload: Any) -> None:
    """Write one deterministic JSON artifact to disk.

    Args:
        path: Destination JSON file path.
        payload: JSON-compatible payload to serialize.

    Returns:
        None.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Run the example and print the resulting summary."""

    summary = run_example()
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
