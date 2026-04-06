"""From-scratch end-to-end converter pipeline example."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ai_converter.compiler import compile_mapping_ir
from ai_converter.drift import apply_converter_patch, classify_drift, propose_compatible_patch
from ai_converter.llm import LLMCallBudgetPolicy, OpenAILLMAdapter
from ai_converter.mapping_ir import MappingIRValidator, MappingSynthesizer
from ai_converter.profiling import build_profile_report
from ai_converter.schema import build_target_schema_card, normalize_source_schema_spec
from ai_converter.validation import validate_structural_output

EXAMPLE_ROOT = Path(__file__).resolve().parent
BASELINE_SAMPLE_DIR = EXAMPLE_ROOT / "source_samples"
DRIFT_SAMPLE_DIR = EXAMPLE_ROOT / "drift_samples"
CONVERT_RECORD_PATH = EXAMPLE_ROOT / "convert_record.json"
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "generated"

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_API_TOKEN = "replace-with-api-token"
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
    if mapping_result.best_candidate is None:
        raise RuntimeError("Mapping synthesis did not produce a valid candidate.")

    for candidate in mapping_result.candidates:
        _write_json(
            output_root / f"mapping_candidate_{candidate.index}.trace.json",
            candidate.response.to_trace_artifact(),
        )

    mapping_ir = mapping_result.best_candidate
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
        "converter_manifest_path": str(export.manifest_path),
        "converted_payload_path": str(output_root / "converted_payload.json"),
        "drift_report_path": str(output_root / "drift_report.json"),
        "drift_resolution_path": str(output_root / "drift_resolution.json"),
        "patched_source_schema_path": patched_source_schema_path,
        "patched_mapping_ir_path": patched_mapping_ir_path,
        "mapping_candidate_count": len(mapping_result.candidates),
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
