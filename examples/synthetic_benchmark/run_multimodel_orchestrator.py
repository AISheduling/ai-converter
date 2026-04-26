"""Run static and LLM-driven synthetic benchmarks plus multi-model converter synthesis."""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field

from ai_converter.compiler import compile_mapping_ir
from ai_converter.evaluation import (
    BenchmarkCase,
    BenchmarkScenario,
    BenchmarkStageArtifacts,
    BenchmarkSubject,
    export_benchmark_experiment_reports,
    run_repeated_benchmark,
)
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
from ai_converter.profiling.loaders import LoadedInput
from ai_converter.schema import (
    SourceFieldSpec,
    SourceSchemaSpec,
    TargetSchemaCard,
    build_target_schema_card,
    normalize_source_schema_spec,
)
from ai_converter.synthetic_benchmark import (
    BundleStore,
    DatasetBundle,
    DriftSpec,
    L0TemplateSpec,
    ScenarioSamplerConfig,
    SyntheticTemplateLLMGenerator,
    TemplateGenerationRequest,
    sample_canonical_scenario,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "examples" / "synthetic_benchmark" / "generated" / "multimodel_orchestrator"
DEFAULT_CREATED_AT = "2026-04-08T00:00:00+00:00"
DEFAULT_SCENARIO_SEED = 11
DEFAULT_TASK_COUNT = 3
DEFAULT_BENCHMARK_RUN_COUNT = 1
SCHEMA_BUDGET = 1800
MAPPING_CANDIDATE_COUNT = 2
MAPPING_REPAIR_BUDGET = 1
REQUIRED_TASK_FIELDS = ("id", "name", "status", "duration_days", "tags")
REQUIRED_SOURCE_SEMANTICS = ("id", "name", "status", "duration_days", "tags", "assignee")
STATIC_DATASET_NAME = "static"
LLM_DYNAMIC_DATASET_NAME = "llm_dynamic"


@dataclass(frozen=True, slots=True)
class ModelEndpointConfig:
    """OpenAI-compatible endpoint configuration used by the orchestration script."""

    name: str
    model: str
    api_token: str
    base_url: str


TEMPLATE_GENERATOR_ENDPOINT = ModelEndpointConfig(
    name="template_generator",
    model="gpt-5.4-nano",
    api_token="sk-YC-5jIbOpjlDRyxc8z8zNA",
    base_url="https://api.duckduck.cloud/v1",
)

CONVERTER_MODEL_ENDPOINTS = (
    ModelEndpointConfig(
        name="gpt_5_4_nano",
        model="gpt-5.4-nano",
        api_token="sk-YC-5jIbOpjlDRyxc8z8zNA",
        base_url="https://api.duckduck.cloud/v1",
    ),
    ModelEndpointConfig(
        name="gpt_5_4_mini",
        model="gpt-5.4-mini",
        api_token="sk-YC-5jIbOpjlDRyxc8z8zNA",
        base_url="https://api.duckduck.cloud/v1",
    ),
)

TEMPLATE_GUIDANCE_NOTES = (
    "Keep one stable record shape across every row in the dataset.",
    "Do not use shape variants, record-specific envelopes, or per-row alias changes.",
    "Preserve semantic coverage for id, name, status, duration_days, assignee, and tags.",
    "You may rename fields or wrap the task inside one nested object, but keep the payload JSON-safe.",
)

CONVERSION_HINT = (
    "Map one synthetic source task record into one target task payload with fields "
    "id, name, status, duration_days, assignee, and tags. The source may rename the "
    "status field or move it into a nested object in drifted rows. Preserve tags as a list "
    "and keep duration_days as an integer."
)


class SyntheticBenchmarkTask(BaseModel):
    """Target-side synthetic task used by benchmark validation."""

    id: str = Field(description="Stable task identifier.")
    name: str = Field(description="Human-readable task title.")
    status: str = Field(description="Workflow status.")
    duration_days: int = Field(description="Planned task duration in days.")
    assignee: str | None = Field(default=None, description="Optional task owner.")
    tags: list[str] = Field(default_factory=list, description="Task tags.")


@dataclass(slots=True)
class DatasetArtifacts:
    """Generated dataset plus bundle, template, and benchmark metadata."""

    dataset_name: str
    dataset_id: str
    dataset_dir: Path
    template: L0TemplateSpec
    bundles: list[DatasetBundle]
    scenarios: list[BenchmarkScenario]
    manifest_path: Path
    template_path: Path
    bundle_dirs: dict[str, Path]
    template_generation_result_path: Path | None = None


def run_orchestrator(
    *,
    output_dir: str | Path | None = None,
    scenario_seed: int = DEFAULT_SCENARIO_SEED,
    task_count: int = DEFAULT_TASK_COUNT,
    benchmark_run_count: int = DEFAULT_BENCHMARK_RUN_COUNT,
    template_generation_client: Any | None = None,
    converter_clients: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full static-vs-dynamic benchmark and converter matrix workflow.

    Args:
        output_dir: Directory where generated artifacts should be written.
        scenario_seed: Deterministic seed used for canonical scenario sampling.
        task_count: Number of synthetic tasks per benchmark bundle.
        benchmark_run_count: Number of repeated benchmark executions per converter.
        template_generation_client: Optional injected OpenAI-compatible client for
            LLM template generation.
        converter_clients: Optional mapping from converter endpoint name to injected
            OpenAI-compatible clients used for converter synthesis.

    Returns:
        JSON-compatible summary of dataset and converter-generation artifacts.
    """

    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    sampled = sample_canonical_scenario(
        scenario_seed,
        ScenarioSamplerConfig(
            task_count=task_count,
            include_assignees=True,
            include_tags=True,
        ),
    )

    datasets = [
        _build_static_dataset(sampled=sampled, output_dir=resolved_output_dir / "datasets" / STATIC_DATASET_NAME),
        _build_dynamic_dataset(
            sampled=sampled,
            output_dir=resolved_output_dir / "datasets" / LLM_DYNAMIC_DATASET_NAME,
            template_generation_client=template_generation_client,
        ),
    ]

    converter_summaries: list[dict[str, Any]] = []
    converter_client_map = dict(converter_clients or {})
    for dataset in datasets:
        for endpoint in CONVERTER_MODEL_ENDPOINTS:
            converter_summaries.append(
                _run_converter_generation(
                    dataset=dataset,
                    endpoint=endpoint,
                    output_dir=resolved_output_dir / "converter_runs" / dataset.dataset_name / endpoint.name,
                    benchmark_run_count=benchmark_run_count,
                    client=converter_client_map.get(endpoint.name),
                )
            )

    summary = {
        "output_dir": str(resolved_output_dir),
        "scenario_seed": scenario_seed,
        "task_count": task_count,
        "benchmark_run_count": benchmark_run_count,
        "template_generator_endpoint": _endpoint_payload(TEMPLATE_GENERATOR_ENDPOINT),
        "converter_endpoints": [
            _endpoint_payload(endpoint)
            for endpoint in CONVERTER_MODEL_ENDPOINTS
        ],
        "datasets": [
            {
                "dataset_name": dataset.dataset_name,
                "dataset_id": dataset.dataset_id,
                "dataset_dir": str(dataset.dataset_dir),
                "manifest_path": str(dataset.manifest_path),
                "template_path": str(dataset.template_path),
                "bundle_dirs": {
                    bundle_name: str(bundle_dir)
                    for bundle_name, bundle_dir in sorted(dataset.bundle_dirs.items())
                },
                "scenario_names": [scenario.name for scenario in dataset.scenarios],
                "template_generation_result_path": (
                    str(dataset.template_generation_result_path)
                    if dataset.template_generation_result_path is not None
                    else None
                ),
            }
            for dataset in datasets
        ],
        "converter_runs": converter_summaries,
    }
    summary_path = resolved_output_dir / "summary.json"
    _write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary


def main() -> int:
    """Run the orchestrator from the command line.

    Args:
        None.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Generate static and LLM-driven synthetic benchmarks, then synthesize "
            "and benchmark converters across multiple model configs."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where experiment artifacts should be written.",
    )
    parser.add_argument(
        "--scenario-seed",
        type=int,
        default=DEFAULT_SCENARIO_SEED,
        help="Seed used for deterministic synthetic scenario generation.",
    )
    parser.add_argument(
        "--task-count",
        type=int,
        default=DEFAULT_TASK_COUNT,
        help="Number of tasks to sample into each synthetic dataset.",
    )
    parser.add_argument(
        "--benchmark-run-count",
        type=int,
        default=DEFAULT_BENCHMARK_RUN_COUNT,
        help="Number of repeated benchmark runs per synthesized converter.",
    )
    args = parser.parse_args()
    summary = run_orchestrator(
        output_dir=args.output_dir,
        scenario_seed=args.scenario_seed,
        task_count=args.task_count,
        benchmark_run_count=args.benchmark_run_count,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _build_static_dataset(
    *,
    sampled: Any,
    output_dir: Path,
) -> DatasetArtifacts:
    """Build the deterministic static synthetic dataset.

    Args:
        sampled: Canonical sampled synthetic scenario with reproducibility metadata.
        output_dir: Dataset output directory.

    Returns:
        Dataset artifacts for the deterministic template baseline.
    """

    return _build_dataset_from_template(
        sampled=sampled,
        dataset_name=STATIC_DATASET_NAME,
        dataset_id="synthetic-static",
        output_dir=output_dir,
        template=L0TemplateSpec(),
    )


def _build_dynamic_dataset(
    *,
    sampled: Any,
    output_dir: Path,
    template_generation_client: Any | None,
) -> DatasetArtifacts:
    """Build the LLM-driven synthetic dataset.

    Args:
        sampled: Canonical sampled synthetic scenario with reproducibility metadata.
        output_dir: Dataset output directory.
        template_generation_client: Optional injected OpenAI-compatible client used
            instead of live network access.

    Returns:
        Dataset artifacts for the LLM-generated template benchmark.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_endpoint_ready(
        TEMPLATE_GENERATOR_ENDPOINT,
        client=template_generation_client,
        purpose="LLM template generation",
    )
    adapter = OpenAILLMAdapter(
        model=TEMPLATE_GENERATOR_ENDPOINT.model,
        api_key=TEMPLATE_GENERATOR_ENDPOINT.api_token,
        base_url=TEMPLATE_GENERATOR_ENDPOINT.base_url,
        client=template_generation_client,
    )
    generator = SyntheticTemplateLLMGenerator(adapter)
    request = TemplateGenerationRequest(
        dataset_id="synthetic-llm-dynamic",
        guidance_notes=list(TEMPLATE_GUIDANCE_NOTES),
        llm_model_config={
            "model": TEMPLATE_GENERATOR_ENDPOINT.model,
            "base_url": TEMPLATE_GENERATOR_ENDPOINT.base_url,
        },
    )
    result = generator.generate(
        request,
        cache_dir=output_dir / "template_cache",
    )
    template_generation_dir = output_dir / "template_generation"
    template_generation_dir.mkdir(parents=True, exist_ok=True)
    result_path = template_generation_dir / "template_generation_result.json"
    _write_json(result_path, result.model_dump(mode="json"))
    for attempt in result.attempts:
        _write_json(
            template_generation_dir / f"attempt_{attempt.attempt}.trace.json",
            attempt.response_trace,
        )
        _write_json(
            template_generation_dir / f"attempt_{attempt.attempt}.validation.json",
            attempt.validation_report.model_dump(mode="json"),
        )
    if result.cache_entry is not None:
        _write_json(
            template_generation_dir / "cache_entry.json",
            result.cache_entry.model_dump(mode="json"),
        )
    if result.accepted_template is None:
        raise RuntimeError(
            "Dynamic template generation did not produce an accepted template: "
            f"{result.failure_reason or result.status}"
        )

    stabilized_template = result.accepted_template
    if stabilized_template.shape_variant_policy is not None:
        stabilized_template = stabilized_template.model_copy(
            update={"shape_variant_policy": None}
        )
        _write_json(
            template_generation_dir / "template_stabilization_note.json",
            {
                "shape_variant_policy_removed": True,
                "reason": (
                    "The benchmark orchestrator keeps one stable per-row schema so that "
                    "downstream converter synthesis sees a single consistent surface."
                ),
            },
        )

    dataset = _build_dataset_from_template(
        sampled=sampled,
        dataset_name=LLM_DYNAMIC_DATASET_NAME,
        dataset_id="synthetic-llm-dynamic",
        output_dir=output_dir,
        template=stabilized_template,
    )
    return DatasetArtifacts(
        dataset_name=dataset.dataset_name,
        dataset_id=dataset.dataset_id,
        dataset_dir=dataset.dataset_dir,
        template=dataset.template,
        bundles=dataset.bundles,
        scenarios=dataset.scenarios,
        manifest_path=dataset.manifest_path,
        template_path=dataset.template_path,
        bundle_dirs=dataset.bundle_dirs,
        template_generation_result_path=result_path,
    )


def _build_dataset_from_template(
    *,
    sampled: Any,
    dataset_name: str,
    dataset_id: str,
    output_dir: Path,
    template: L0TemplateSpec,
) -> DatasetArtifacts:
    """Materialize one dataset from a concrete template.

    Args:
        sampled: Canonical sampled synthetic scenario with reproducibility metadata.
        dataset_name: Stable dataset label used in artifact paths.
        dataset_id: Stable dataset id embedded into bundle metadata.
        output_dir: Dataset output directory.
        template: Template used to render the synthetic L0 bundles.

    Returns:
        Complete dataset artifacts including saved bundles and benchmark scenarios.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    template_path = output_dir / "template.json"
    _write_json(template_path, template.model_dump(mode="json"))

    store = BundleStore()
    base_bundle = store.build_bundle(
        sampled,
        template,
        dataset_id=dataset_id,
        bundle_id=f"{dataset_name}-base",
        created_at=DEFAULT_CREATED_AT,
    )
    drift_specs = _build_drift_specs(
        template,
        record_indexes=list(range(len(base_bundle.scenario.tasks))),
    )
    rename_bundle = store.build_drift_bundle(
        base_bundle,
        drift_specs["rename"],
        bundle_id=f"{dataset_name}-drift-rename",
        created_at=DEFAULT_CREATED_AT,
    )
    nesting_bundle = store.build_drift_bundle(
        base_bundle,
        drift_specs["nesting"],
        bundle_id=f"{dataset_name}-drift-nesting",
        created_at=DEFAULT_CREATED_AT,
    )
    bundles = [base_bundle, rename_bundle, nesting_bundle]

    bundle_dirs: dict[str, Path] = {}
    for bundle in bundles:
        directory_name = bundle.metadata.bundle_id.replace("_", "-")
        bundle_dir = output_dir / "bundles" / directory_name
        store.save(bundle, bundle_dir)
        bundle_dirs[bundle.metadata.bundle_id] = bundle_dir

    scenarios = [
        _build_task_benchmark_scenario(dataset_name, bundle)
        for bundle in bundles
    ]
    manifest = {
        "dataset_name": dataset_name,
        "dataset_id": dataset_id,
        "template_id": template.template_id,
        "bundle_ids": [bundle.metadata.bundle_id for bundle in bundles],
        "bundle_kind_by_id": {
            bundle.metadata.bundle_id: bundle.metadata.bundle_kind
            for bundle in bundles
        },
        "scenario_names": [scenario.name for scenario in scenarios],
        "template_path": str(template_path),
        "bundle_dirs": {
            bundle_name: str(bundle_dir)
            for bundle_name, bundle_dir in sorted(bundle_dirs.items())
        },
    }
    manifest_path = output_dir / "dataset_manifest.json"
    _write_json(manifest_path, manifest)
    return DatasetArtifacts(
        dataset_name=dataset_name,
        dataset_id=dataset_id,
        dataset_dir=output_dir,
        template=template,
        bundles=bundles,
        scenarios=scenarios,
        manifest_path=manifest_path,
        template_path=template_path,
        bundle_dirs=bundle_dirs,
    )


def _run_converter_generation(
    *,
    dataset: DatasetArtifacts,
    endpoint: ModelEndpointConfig,
    output_dir: Path,
    benchmark_run_count: int,
    client: Any | None,
) -> dict[str, Any]:
    """Generate, compile, and benchmark one converter model on one dataset.

    Args:
        dataset: Dataset artifacts used as source evidence and benchmark fixtures.
        endpoint: Converter model endpoint configuration.
        output_dir: Directory where run artifacts should be written.
        benchmark_run_count: Number of repeated benchmark executions.
        client: Optional injected OpenAI-compatible client.

    Returns:
        Machine-readable summary for the dataset/model run.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_endpoint_ready(
        endpoint,
        client=client,
        purpose=f"converter generation for dataset {dataset.dataset_name}",
    )
    profile_input = _build_profile_input(dataset.bundles)
    profile_report = build_profile_report(profile_input, sample_limit=3)
    _write_json(output_dir / "profile_report.json", profile_report.model_dump(mode="json"))

    target_schema = build_target_schema_card(SyntheticBenchmarkTask)
    _write_json(output_dir / "target_schema_card.json", target_schema.model_dump(mode="json"))

    synthesizer = MappingSynthesizer(
        OpenAILLMAdapter(
            model=endpoint.model,
            api_key=endpoint.api_token,
            base_url=endpoint.base_url,
            client=client,
        ),
        budget_policy=LLMCallBudgetPolicy(
            schema=1,
            mapping=MAPPING_CANDIDATE_COUNT,
            repair=MAPPING_REPAIR_BUDGET,
        ),
    )

    schema_response = synthesizer.synthesize_source_schema(
        profile_report,
        budget=SCHEMA_BUDGET,
        mode="balanced",
        format_hint="synthetic task row json examples",
        required_semantic_paths=_build_required_semantic_paths_from_profile(profile_report),
        metadata={
            "dataset": dataset.dataset_name,
            "model": endpoint.model,
            "stage": "schema",
            "workflow": "multimodel_orchestrator",
        },
    )
    source_schema = normalize_source_schema_spec(
        _require_parsed(schema_response, label="source schema")
    )
    if source_schema.schema_fingerprint is None:
        source_schema = source_schema.model_copy(
            update={"schema_fingerprint": profile_report.schema_fingerprint}
        )
    _write_json(output_dir / "source_schema.llm.json", source_schema.model_dump(mode="json"))
    source_schema, schema_completion_report = _complete_source_schema_from_profile(
        source_schema,
        profile_report,
    )
    schema_coverage_report = _build_schema_coverage_report(source_schema)
    _write_json(
        output_dir / "source_schema.trace.json",
        schema_response.to_trace_artifact(),
    )
    _write_json(output_dir / "source_schema_completion.json", schema_completion_report)
    _write_json(output_dir / "schema_coverage.json", schema_coverage_report)
    _write_json(output_dir / "source_schema.json", source_schema.model_dump(mode="json"))
    if schema_coverage_report["missing_required_semantics"]:
        raise RuntimeError(
            "Completed source schema still lacks required semantics: "
            + ", ".join(schema_coverage_report["missing_required_semantics"])
        )

    mapping_conversion_hint = _build_mapping_conversion_hint(
        CONVERSION_HINT,
        profile_report,
        schema_coverage_report=schema_coverage_report,
    )
    mapping_result = synthesizer.synthesize_mapping(
        source_schema,
        target_schema,
        candidate_count=MAPPING_CANDIDATE_COUNT,
        conversion_hint=mapping_conversion_hint,
        required_semantic_paths=_build_required_semantic_paths_from_schema(source_schema),
        metadata={
            "dataset": dataset.dataset_name,
            "model": endpoint.model,
            "stage": "mapping",
            "workflow": "multimodel_orchestrator",
        },
    )
    for candidate in mapping_result.candidates:
        _write_json(
            output_dir / f"mapping_candidate_{candidate.index}.trace.json",
            candidate.response.to_trace_artifact(),
        )

    mapping_ir, mapping_selection = _select_mapping_candidate(
        mapping_result,
        source_schema=source_schema,
        target_schema=target_schema,
        smoke_scenarios=dataset.scenarios,
    )
    mapping_preflight_report = _build_mapping_preflight_report(
        mapping_ir,
        source_schema=source_schema,
    )
    mapping_validation = MappingIRValidator().validate(
        mapping_ir,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    if not mapping_validation.valid:
        raise RuntimeError(
            "Synthesized MappingIR did not validate: "
            + "; ".join(
                f"{issue.location}: {issue.message}"
                for issue in mapping_validation.issues
            )
        )
    _write_json(output_dir / "mapping_selection.json", mapping_selection)
    _write_json(output_dir / "mapping_validation.json", mapping_validation.model_dump(mode="json"))
    _write_json(output_dir / "mapping_preflight.json", mapping_preflight_report)
    _write_json(output_dir / "mapping_ir.json", mapping_ir.model_dump(mode="json"))

    package = compile_mapping_ir(
        mapping_ir,
        module_name=f"{dataset.dataset_name}_{endpoint.name}_converter",
    )
    export = package.export(output_dir / "converter_package")

    experiment = run_repeated_benchmark(
        [
            BenchmarkSubject.from_converter_package(
                endpoint.name,
                package,
                kind="compiled",
                stage_artifacts=BenchmarkStageArtifacts(
                    source_structure_recovery=1.0,
                    mapping_quality=1.0 if mapping_validation.valid else 0.0,
                    artifacts={
                        "dataset_name": dataset.dataset_name,
                        "model": endpoint.model,
                        "source_schema_path": str(output_dir / "source_schema.json"),
                        "mapping_ir_path": str(output_dir / "mapping_ir.json"),
                    },
                ),
            )
        ],
        dataset.scenarios,
        run_count=benchmark_run_count,
        experiment_name=f"{dataset.dataset_name}-{endpoint.name}",
    )
    benchmark_paths = export_benchmark_experiment_reports(
        experiment,
        output_dir / "benchmark",
        stem="benchmark",
        include_telemetry=True,
    )
    benchmark_metrics = _summarize_benchmark_experiment(experiment)

    summary = {
        "dataset_name": dataset.dataset_name,
        "model_name": endpoint.name,
        "model": endpoint.model,
        "run_dir": str(output_dir),
        "profile_report_path": str(output_dir / "profile_report.json"),
        "source_schema_llm_path": str(output_dir / "source_schema.llm.json"),
        "source_schema_path": str(output_dir / "source_schema.json"),
        "source_schema_completion_report_path": str(output_dir / "source_schema_completion.json"),
        "schema_coverage_report_path": str(output_dir / "schema_coverage.json"),
        "mapping_ir_path": str(output_dir / "mapping_ir.json"),
        "mapping_selection_path": str(output_dir / "mapping_selection.json"),
        "mapping_preflight_report_path": str(output_dir / "mapping_preflight.json"),
        "converter_manifest_path": str(export.manifest_path),
        "benchmark_experiment_json_path": str(benchmark_paths["experiment_json"]),
        "benchmark_markdown_path": str(benchmark_paths["experiment_markdown"]),
        "benchmark_summary_json_path": str(benchmark_paths["summary_json"]),
        "benchmark_summary_csv_path": str(benchmark_paths["summary_csv"]),
        "benchmark_boxplot_csv_path": str(benchmark_paths["boxplot_csv"]),
        "telemetry_summary_json_path": (
            str(benchmark_paths["telemetry_summary_json"])
            if "telemetry_summary_json" in benchmark_paths
            else None
        ),
        "mapping_candidate_count": len(mapping_result.candidates),
        "selected_mapping_candidate_index": mapping_selection["selected_candidate_index"],
        "mapping_repair_applied": bool(mapping_selection.get("repair_applied")),
        "mapping_validation": mapping_validation.model_dump(mode="json"),
        "schema_completion_report": schema_completion_report,
        "schema_coverage_report": schema_coverage_report,
        "mapping_preflight_report": mapping_preflight_report,
        "semantic_preflight_report": mapping_preflight_report,
        "budget_accounting": (
            mapping_result.budget_accounting.to_dict()
            if mapping_result.budget_accounting is not None
            else None
        ),
        "benchmark_metrics": benchmark_metrics,
    }
    summary_path = output_dir / "summary.json"
    _write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary


def _build_profile_input(bundles: Sequence[DatasetBundle]) -> LoadedInput:
    """Flatten bundle rows into one profiling input for source-schema synthesis.

    Args:
        bundles: Synthetic bundles whose L0 task rows should be profiled together.

    Returns:
        In-memory profiling input containing one source record per synthetic task row.
    """

    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        rows.extend(copy.deepcopy(_extract_l0_rows(bundle)))
    return LoadedInput(
        kind="json",
        path="synthetic_task_rows.json",
        records=rows,
        root_type="rows",
    )


def _build_task_benchmark_scenario(
    dataset_name: str,
    bundle: DatasetBundle,
) -> BenchmarkScenario:
    """Create one benchmark scenario that evaluates individual task rows.

    Args:
        dataset_name: Stable dataset label used in scenario names and tags.
        bundle: Synthetic bundle whose rows become benchmark cases.

    Returns:
        Benchmark scenario that evaluates one source row at a time.
    """

    records = _extract_l0_rows(bundle)
    expected_tasks = _extract_expected_tasks(bundle)
    cases: list[BenchmarkCase] = []
    for index, (record, expected_task) in enumerate(zip(records, expected_tasks, strict=True)):
        task_id = str(expected_task["id"])
        tags = _dedupe_tags(
            [
                *_bundle_tags(bundle, dataset_name),
                f"bundle:{bundle.metadata.bundle_id}",
                f"task:{task_id}",
                f"row_index:{index}",
            ]
        )
        cases.append(
            BenchmarkCase(
                name=f"{bundle.metadata.bundle_id}:{task_id}",
                record=copy.deepcopy(record),
                expected_output=copy.deepcopy(expected_task),
                required_fields=list(REQUIRED_TASK_FIELDS),
                tags=tags,
            )
        )
    return BenchmarkScenario(
        name=bundle.metadata.bundle_id,
        cases=cases,
        target_model=SyntheticBenchmarkTask,
        tags=_bundle_tags(bundle, dataset_name),
    )


def _extract_l0_rows(bundle: DatasetBundle) -> list[dict[str, Any]]:
    """Return the task rows rendered inside one synthetic L0 payload.

    Args:
        bundle: Synthetic bundle whose L0 payload should be unpacked.

    Returns:
        List of task-row dictionaries.

    Raises:
        TypeError: If the bundle payload does not contain object rows.
    """

    payload = bundle.l0_payload
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise TypeError("Synthetic list-root L0 payload must contain dictionaries")
        return list(payload)
    if not isinstance(payload, dict):
        raise TypeError("Synthetic object-root L0 payload must be a dictionary")
    records = payload.get(bundle.template.records_key)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise TypeError(
            f"Synthetic object-root L0 payload must contain a list of dictionaries at {bundle.template.records_key!r}"
        )
    return list(records)


def _extract_expected_tasks(bundle: DatasetBundle) -> list[dict[str, Any]]:
    """Return the target-side synthetic tasks for one bundle.

    Args:
        bundle: Synthetic bundle whose L1 payload should be unpacked.

    Returns:
        Target-side task dictionaries aligned with the source rows.
    """

    payload = bundle.l1_payload
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not all(isinstance(item, dict) for item in tasks):
        raise TypeError("Synthetic L1 payload must expose tasks as list[dict]")
    return list(tasks)


def _bundle_tags(bundle: DatasetBundle, dataset_name: str) -> list[str]:
    """Build deterministic benchmark tags for one dataset bundle.

    Args:
        bundle: Synthetic bundle being adapted into benchmark fixtures.
        dataset_name: Dataset label that owns the bundle.

    Returns:
        Deduplicated tag list.
    """

    tags = [
        "synthetic",
        bundle.metadata.bundle_kind,
        f"dataset_name:{dataset_name}",
        f"dataset:{bundle.metadata.dataset_id}",
        f"template:{bundle.metadata.source_template_id}",
    ]
    if bundle.drift_manifest is not None:
        tags.extend(
            [
                "drift",
                f"drift_id:{bundle.drift_manifest.drift_id}",
                f"drift_type:{bundle.drift_manifest.drift_type}",
                f"severity:{bundle.drift_manifest.severity}",
                f"compatibility:{bundle.drift_manifest.compatibility_class}",
            ]
        )
    return _dedupe_tags(tags)


def _build_drift_specs(
    template: L0TemplateSpec,
    *,
    record_indexes: list[int],
) -> dict[str, DriftSpec]:
    """Build rename and nesting drift specs for one template surface.

    Args:
        template: Base L0 template used to render the stable rows.
        record_indexes: Row indexes that should receive the drift.

    Returns:
        Mapping from drift kind label to drift spec.
    """

    status_path = _task_field_path(template, "status")
    renamed_status_path = _replace_leaf(status_path, f"{_leaf_name(status_path)}_label")
    parent_path = _parent_path(status_path)
    nested_status_path = (
        f"{parent_path}.status.details"
        if parent_path is not None
        else "status.details"
    )
    return {
        "rename": DriftSpec.model_validate(
            {
                "version": "1.0",
                "drift_id": "rename-status",
                "drift_type": "rename",
                "severity": "low",
                "compatibility_class": "rename_compatible",
                "operators": [
                    {
                        "kind": "rename_field",
                        "path": status_path,
                        "new_path": renamed_status_path,
                        "record_indexes": record_indexes,
                    }
                ],
                "notes": [
                    "Rename the status field while keeping it semantically compatible."
                ],
            }
        ),
        "nesting": DriftSpec.model_validate(
            {
                "version": "1.0",
                "drift_id": "nest-status",
                "drift_type": "nesting",
                "severity": "high",
                "compatibility_class": "breaking_change",
                "operators": [
                    {
                        "kind": "nest_field",
                        "path": status_path,
                        "new_path": nested_status_path,
                        "record_indexes": record_indexes,
                    }
                ],
                "notes": [
                    "Move the status field into a nested object to create a structure-changing drift."
                ],
            }
        ),
    }


def _task_field_path(template: L0TemplateSpec, field_name: str) -> str:
    """Resolve the rendered path for one canonical task field.

    Args:
        template: Template whose alias surface should be inspected.
        field_name: Canonical field name on ``TaskFieldAliases``.

    Returns:
        Dotted source path for the rendered field.
    """

    alias = getattr(template.field_aliases, field_name)
    if template.wrap_task_object:
        return f"{template.task_object_key}.{alias}"
    return alias


def _replace_leaf(path: str, new_leaf: str) -> str:
    """Replace the final path segment in a dotted source path.

    Args:
        path: Existing dotted path.
        new_leaf: Replacement leaf segment.

    Returns:
        Path with the same parent segments and a new leaf.
    """

    parent = _parent_path(path)
    if parent is None:
        return new_leaf
    return f"{parent}.{new_leaf}"


def _parent_path(path: str) -> str | None:
    """Return the parent portion of a dotted path.

    Args:
        path: Candidate dotted path.

    Returns:
        Parent path when present, otherwise ``None``.
    """

    parts = path.split(".")
    if len(parts) == 1:
        return None
    return ".".join(parts[:-1])


def _leaf_name(path: str) -> str:
    """Return the final segment of a dotted path.

    Args:
        path: Candidate dotted path.

    Returns:
        Final path segment.
    """

    return path.split(".")[-1]


def _endpoint_payload(endpoint: ModelEndpointConfig) -> dict[str, str]:
    """Return a serializable endpoint description without exposing secrets.

    Args:
        endpoint: Endpoint configuration to serialize.

    Returns:
        JSON-compatible endpoint payload.
    """

    return {
        "name": endpoint.name,
        "model": endpoint.model,
        "base_url": endpoint.base_url,
        "api_token_configured": bool(
            endpoint.api_token and not endpoint.api_token.startswith("replace-")
        ),
    }


def _ensure_endpoint_ready(
    endpoint: ModelEndpointConfig,
    *,
    client: Any | None,
    purpose: str,
) -> None:
    """Raise a clear error when a live endpoint is not configured.

    Args:
        endpoint: Endpoint configuration being used.
        client: Optional injected fake or prebuilt client.
        purpose: Human-readable description of the current workflow stage.

    Returns:
        None.

    Raises:
        RuntimeError: If the script would need live credentials that are still placeholders.
    """

    if client is not None:
        return
    if not endpoint.api_token or endpoint.api_token.startswith("replace-"):
        raise RuntimeError(
            f"Configure a real api_token constant for {purpose} before running the live workflow: {endpoint.name}"
        )
    if not endpoint.base_url.strip():
        raise RuntimeError(
            f"Configure a non-empty base_url constant for {purpose}: {endpoint.name}"
        )


def _complete_source_schema_from_profile(
    source_schema: SourceSchemaSpec,
    profile_report: Any,
) -> tuple[SourceSchemaSpec, dict[str, Any]]:
    """Backfill LLM-omitted schema fields from deterministic profile evidence.

    Args:
        source_schema: LLM-generated and normalized source schema.
        profile_report: Deterministic profile report for the same dataset rows.

    Returns:
        Completed source schema and a machine-readable completion report.
    """

    fields = list(source_schema.fields)
    existing_paths = {field.path for field in fields}
    added_fields: list[SourceFieldSpec] = []
    for field_profile in profile_report.field_profiles:
        if field_profile.path in existing_paths:
            continue
        added_field = _source_field_from_profile(field_profile)
        fields.append(added_field)
        existing_paths.add(added_field.path)
        added_fields.append(added_field)

    completed_schema = source_schema.model_copy(
        update={
            "schema_fingerprint": profile_report.schema_fingerprint,
            "fields": sorted(fields, key=lambda field: field.path),
        }
    )
    report = {
        "field_count_before": len(source_schema.fields),
        "field_count_after": len(completed_schema.fields),
        "kept_paths": sorted(field.path for field in source_schema.fields),
        "added_paths": [field.path for field in added_fields],
        "added_fields": [field.model_dump(mode="json") for field in added_fields],
    }
    return completed_schema, report


def _source_field_from_profile(field_profile: Any) -> SourceFieldSpec:
    """Build one deterministic SourceFieldSpec from a profiling field row."""

    observed_types = [
        observed.type_name
        for observed in field_profile.observed_types
        if observed.type_name
    ]
    dtype = _dtype_from_profile(field_profile, observed_types)
    semantic_name = _infer_semantic_name(field_profile.path)
    return SourceFieldSpec(
        path=field_profile.path,
        semantic_name=semantic_name,
        dtype=dtype,
        cardinality=_cardinality_from_profile(field_profile, observed_types),
        nullable=field_profile.null_ratio > 0 or field_profile.present_ratio < 1,
        aliases=_dedupe_preserve_order(
            [
                semantic_name,
                _leaf_name(field_profile.path.replace("[]", "")),
                _slugify_identifier(field_profile.path),
                *field_profile.original_names,
            ]
        ),
        examples=list(field_profile.sample_values[:5]),
        confidence=0.5,
        description="Deterministically backfilled from profile evidence.",
    )


def _dtype_from_profile(field_profile: Any, observed_types: Sequence[str]) -> str:
    """Infer the schema dtype from observed profiling types."""

    if "list" in observed_types:
        return "list"
    if observed_types:
        return observed_types[0]
    if field_profile.path.endswith("[]"):
        return "str"
    return "unknown"


def _cardinality_from_profile(field_profile: Any, observed_types: Sequence[str]) -> str:
    """Infer source-field cardinality from profile evidence."""

    if field_profile.path.endswith("[]") or "list" in observed_types:
        return "many"
    return "one"


def _infer_semantic_name(path: str) -> str:
    """Infer a stable semantic name from a profiled source path."""

    clean_path = path.replace("[]", "")
    leaf = _leaf_name(clean_path)
    parent = _parent_path(clean_path) or ""
    token = _slugify_identifier(leaf)
    if token in {"id", "task_id", "entity_id"}:
        return "id"
    if token in {"name", "task_name", "title"}:
        return "name"
    if token in {"duration", "duration_days", "days"}:
        return "duration_days"
    if token in {"assignee", "owner"}:
        return "assignee"
    if token in {"tags", "labels"}:
        return "tags"
    if token in {"status_text_label", "status_label", "state_label"}:
        return "status_label"
    if token in {"status_text", "status", "state"}:
        return "status"
    if token == "details" and "status" in _slugify_identifier(parent):
        return "status_nested"
    return token


def _build_schema_coverage_report(source_schema: SourceSchemaSpec) -> dict[str, Any]:
    """Summarize whether the completed schema covers required semantics."""

    required: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for semantic in REQUIRED_SOURCE_SEMANTICS:
        paths = [
            field.path
            for field in source_schema.fields
            if _field_matches_required_semantic(field, semantic)
        ]
        required[semantic] = {
            "covered": bool(paths),
            "paths": paths,
        }
        if not paths:
            missing.append(semantic)
    return {
        "field_count": len(source_schema.fields),
        "required_semantics": required,
        "missing_required_semantics": missing,
    }


def _build_required_semantic_paths_from_profile(profile_report: Any) -> dict[str, list[str]]:
    """Infer required semantic path hints directly from profile evidence."""

    semantic_paths: dict[str, list[str]] = {}
    inferred_fields = [
        _source_field_from_profile(field_profile)
        for field_profile in profile_report.field_profiles
    ]
    for semantic in REQUIRED_SOURCE_SEMANTICS:
        semantic_paths[semantic] = [
            field.path
            for field in inferred_fields
            if _field_matches_required_semantic(field, semantic)
        ]
    return semantic_paths


def _build_required_semantic_paths_from_schema(source_schema: SourceSchemaSpec) -> dict[str, list[str]]:
    """Build required semantic path hints from the completed source schema."""

    semantic_paths: dict[str, list[str]] = {}
    for semantic in REQUIRED_SOURCE_SEMANTICS:
        semantic_paths[semantic] = [
            field.path
            for field in source_schema.fields
            if _field_matches_required_semantic(field, semantic)
        ]
    return semantic_paths


def _field_matches_required_semantic(field: SourceFieldSpec, semantic: str) -> bool:
    """Return whether a source field can support one required target semantic."""

    tokens = {
        field.semantic_name,
        _leaf_name(field.path.replace("[]", "")),
        _slugify_identifier(field.path),
        *field.aliases,
    }
    normalized_tokens = {_slugify_identifier(token) for token in tokens if token}
    path_slug = _slugify_identifier(field.path)
    if semantic == "id":
        return bool(normalized_tokens & {"id", "task_id", "entity_id"})
    if semantic == "name":
        return bool(normalized_tokens & {"name", "task_name", "title"})
    if semantic == "duration_days":
        return bool(normalized_tokens & {"duration", "duration_days", "days"})
    if semantic == "tags":
        return bool(normalized_tokens & {"tags", "labels", "tag", "label"})
    if semantic == "status":
        return (
            bool(normalized_tokens & {"status", "status_text", "status_label", "state", "state_label"})
            or "status" in path_slug
        )
    return semantic in normalized_tokens


def _build_mapping_conversion_hint(
    base_hint: str,
    profile_report: Any,
    *,
    schema_coverage_report: dict[str, Any],
) -> str:
    """Append compact profiling hints to the mapping synthesis hint."""

    field_lines = []
    for field_profile in profile_report.field_profiles[:24]:
        type_names = ", ".join(
            observed.type_name for observed in field_profile.observed_types
        ) or "unknown"
        examples = ", ".join(field_profile.sample_values[:3])
        field_lines.append(
            f"- {field_profile.path} | types={type_names} | "
            f"present={field_profile.present_ratio:.2f} | examples={examples}"
        )
    coverage_lines = [
        f"- {semantic}: {', '.join(payload['paths']) or 'missing'}"
        for semantic, payload in schema_coverage_report["required_semantics"].items()
    ]
    return (
        f"{base_hint}\n\n"
        "Observed source path hints from deterministic profiling:\n"
        + "\n".join(field_lines)
        + "\n\nRequired semantic coverage after schema completion:\n"
        + "\n".join(coverage_lines)
    )


def _build_mapping_preflight_report(
    mapping_ir: MappingIR,
    *,
    source_schema: SourceSchemaSpec,
) -> dict[str, Any]:
    """Build a semantic preflight report for a selected MappingIR."""

    assignment_by_target = {
        assignment.target_path: assignment.step_id
        for assignment in mapping_ir.assignments
    }
    step_by_id = {step.id: step for step in mapping_ir.steps}
    source_ref_by_id = {source_ref.id: source_ref for source_ref in mapping_ir.source_refs}
    coverage_report = _build_schema_coverage_report(source_schema)
    missing_required_targets = [
        target_path
        for target_path in REQUIRED_TASK_FIELDS
        if target_path not in assignment_by_target
    ]
    warnings: list[dict[str, Any]] = []
    defaulted_required_targets: list[str] = []
    for target_path in REQUIRED_TASK_FIELDS:
        step = step_by_id.get(assignment_by_target.get(target_path, ""))
        if step is None:
            continue
        if step.operation.kind == "default" and step.operation.source_ref is None:
            defaulted_required_targets.append(target_path)
            if coverage_report["required_semantics"].get(target_path, {}).get("covered"):
                warnings.append(
                    {
                        "code": "default_used_while_source_available",
                        "target_path": target_path,
                        "step_id": step.id,
                    }
                )
        if target_path == "status" and step.operation.source_ref is not None:
            status_paths = coverage_report["required_semantics"]["status"]["paths"]
            source_ref = source_ref_by_id.get(step.operation.source_ref)
            if source_ref is not None and len(status_paths) > 1:
                warnings.append(
                    {
                        "code": "status_uses_single_surface",
                        "target_path": target_path,
                        "step_id": step.id,
                        "source_path": source_ref.path,
                        "available_status_paths": status_paths,
                    }
                )
    return {
        "target_assignments": assignment_by_target,
        "missing_required_targets": missing_required_targets,
        "defaulted_required_targets": defaulted_required_targets,
        "warnings": warnings,
    }


def _require_parsed(response: Any, *, label: str) -> Any:
    """Return the parsed adapter payload or raise a helpful error.

    Args:
        response: Adapter response returned by the synthesis layer.
        label: Human-readable label for the expected payload.

    Returns:
        Parsed payload from the response.

    Raises:
        RuntimeError: If the response does not contain a parsed payload.
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
    smoke_scenarios: Sequence[BenchmarkScenario] | None = None,
    repair_budget: int = MAPPING_REPAIR_BUDGET,
) -> tuple[MappingIR, dict[str, Any]]:
    """Pick the best valid mapping candidate using runtime smoke evidence.

    Args:
        mapping_result: Ordered mapping synthesis result returned by the orchestrator.
        source_schema: Canonical source schema available to the current run.
        target_schema: Canonical target schema card.
        smoke_scenarios: Optional benchmark scenarios used for deterministic
            compile/runtime candidate smoke ranking.
        repair_budget: Maximum deterministic repair attempts for smoke-failed
            validator-valid candidates.

    Returns:
        Tuple of selected mapping IR and machine-readable selection report.
    """

    smoke_subset = _build_mapping_candidate_smoke_scenarios(
        smoke_scenarios or [],
        source_schema=source_schema,
    )
    scored_candidates: list[tuple[Any, dict[str, Any]]] = []
    for candidate in mapping_result.candidates:
        if candidate.ranked.validation.valid and candidate.ranked.candidate is not None:
            if not smoke_subset:
                return candidate.ranked.candidate, {
                    "selected_candidate_index": candidate.index,
                    "selection_mode": "direct_valid_candidate",
                    "repair_applied": False,
                    "initial_validation": candidate.ranked.validation.model_dump(mode="json"),
                }
            scored_candidates.append(
                (
                    candidate,
                    _score_mapping_candidate_smoke(
                        candidate.ranked.candidate,
                        candidate_index=candidate.index,
                        validation=candidate.ranked.validation,
                        smoke_scenarios=smoke_subset,
                    ),
                )
            )

    if scored_candidates:
        repair_budget_consumed = 0
        repair_reports: list[dict[str, Any]] = []
        repaired_candidates: list[tuple[Any, MappingIR, dict[str, Any], dict[str, Any]]] = []
        for candidate, score in scored_candidates:
            if repair_budget_consumed >= repair_budget:
                break
            if not _mapping_smoke_score_needs_repair(score):
                continue
            repair_budget_consumed += 1
            repaired_candidate, repair_report = _repair_runtime_smoke_candidate(
                candidate.ranked.candidate,
                candidate_index=candidate.index,
                source_schema=source_schema,
                target_schema=target_schema,
                smoke_scenarios=smoke_subset,
                original_score=score,
                repair_budget_configured=repair_budget,
                repair_budget_consumed=repair_budget_consumed,
            )
            repair_reports.append(repair_report)
            post_repair_score = repair_report.get("post_repair_smoke_score")
            if (
                repair_report["repair_applied"]
                and repair_report["post_repair_validation"]["valid"]
                and post_repair_score is not None
                and post_repair_score["smoke_passed"]
            ):
                repaired_candidates.append(
                    (candidate, repaired_candidate, post_repair_score, repair_report)
                )

        passing_candidates = [
            (candidate, candidate.ranked.candidate, score, None)
            for candidate, score in scored_candidates
            if score["smoke_passed"]
        ]
        passing_candidates.extend(repaired_candidates)
        candidate_scores = [score for _, score in scored_candidates]
        if passing_candidates:
            selected_candidate, selected_program, selected_score, selected_repair_report = max(
                passing_candidates,
                key=lambda item: _mapping_smoke_selection_key(item[2], item[0]),
            )
            if selected_repair_report is not None:
                return selected_program, {
                    "selected_candidate_index": selected_candidate.index,
                    "selection_mode": "runtime_smoke_repaired_candidate",
                    "repair_applied": True,
                    "initial_validation": selected_candidate.ranked.validation.model_dump(mode="json"),
                    "validation_summary": selected_score["validation_summary"],
                    "smoke_score": selected_score["smoke_score"],
                    "candidate_scores": candidate_scores,
                    "repair_report": selected_repair_report,
                    "repair_reports": repair_reports,
                }
            return selected_candidate.ranked.candidate, {
                "selected_candidate_index": selected_candidate.index,
                "selection_mode": "runtime_smoke_ranked_candidate",
                "repair_applied": False,
                "initial_validation": selected_candidate.ranked.validation.model_dump(mode="json"),
                "validation_summary": selected_score["validation_summary"],
                "smoke_score": selected_score["smoke_score"],
                "candidate_scores": candidate_scores,
                "repair_reports": repair_reports,
            }

        detail = "; ".join(
            (
                f"candidate {score['candidate_index']}: "
                f"compile_success={score['compile_success']}, "
                f"execution_success_rate={score['execution_success_rate']:.3f}, "
                f"runtime_errors={score['runtime_errors'] or {}}"
            )
            for score in candidate_scores
        )
        raise RuntimeError(
            "Mapping synthesis produced validator-valid candidates, but none passed "
            f"runtime smoke selection. Details: {detail}"
        )

    diagnostics: list[str] = []
    for candidate in mapping_result.candidates:
        if candidate.response.parsed is None:
            if candidate.response.errors:
                diagnostics.extend(
                    f"candidate {candidate.index}: {error.message}"
                    for error in candidate.response.errors
                )
            else:
                diagnostics.append(
                    f"candidate {candidate.index}: no parsed mapping candidate was returned"
                )
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


def _build_mapping_candidate_smoke_scenarios(
    scenarios: Sequence[BenchmarkScenario],
    *,
    source_schema: SourceSchemaSpec,
) -> list[BenchmarkScenario]:
    """Build a small deterministic smoke subset for MappingIR candidate ranking.

    Args:
        scenarios: Full benchmark scenarios for the current synthetic dataset.
        source_schema: Source schema used to synthesize an optional missing-tags
            smoke case when the sampled scenarios do not contain one.

    Returns:
        A single smoke scenario containing one case per input scenario plus a
        missing-tags case when available or synthesizable.
    """

    selected: list[BenchmarkCase] = []
    selected_keys: set[tuple[str, str]] = set()
    all_cases: list[tuple[str, BenchmarkCase]] = []
    for scenario in scenarios:
        for case in scenario.cases:
            all_cases.append((scenario.name, case))
        if scenario.cases:
            key = (scenario.name, scenario.cases[0].name)
            selected.append(_copy_benchmark_case(scenario.cases[0]))
            selected_keys.add(key)

    missing_tags_case = next(
        (
            (scenario_name, case)
            for scenario_name, case in all_cases
            if not case.expected_output.get("tags")
        ),
        None,
    )
    if (
        missing_tags_case is not None
        and (missing_tags_case[0], missing_tags_case[1].name) not in selected_keys
    ):
        scenario_name, case = missing_tags_case
        selected.append(_copy_benchmark_case(case))
        selected_keys.add((scenario_name, case.name))

    if selected and all(case.expected_output.get("tags") for case in selected):
        selected.append(
            _build_missing_tags_smoke_case(
                selected[0],
                source_schema=source_schema,
            )
        )

    if not selected:
        return []
    target_model = next(
        (scenario.target_model for scenario in scenarios if scenario.target_model is not None),
        None,
    )
    return [
        BenchmarkScenario(
            name="mapping-candidate-runtime-smoke",
            cases=selected,
            target_model=target_model,
            tags=["mapping_candidate_smoke"],
        )
    ]


def _score_mapping_candidate_smoke(
    mapping_ir: MappingIR,
    *,
    candidate_index: int,
    validation: Any,
    smoke_scenarios: Sequence[BenchmarkScenario],
) -> dict[str, Any]:
    """Compile and run one MappingIR candidate against the smoke subset."""

    report: dict[str, Any] = {
        "candidate_index": candidate_index,
        "validation_summary": _validation_summary(validation),
        "compile_success": False,
        "execution_success_rate": 0.0,
        "structural_validity_rate": 0.0,
        "required_field_accuracy": 0.0,
        "runtime_error_count": 0,
        "runtime_errors": {},
        "smoke_score": 0.0,
        "smoke_passed": False,
    }
    try:
        package = compile_mapping_ir(
            mapping_ir,
            module_name=f"mapping_candidate_{candidate_index}_smoke_converter",
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        report["compile_error"] = message
        report["runtime_error_count"] = 1
        report["runtime_errors"] = {message: 1}
        return report

    report["compile_success"] = True
    experiment = run_repeated_benchmark(
        [
            BenchmarkSubject.from_converter_package(
                f"candidate_{candidate_index}",
                package,
                kind="compiled",
            )
        ],
        list(smoke_scenarios),
        run_count=1,
        experiment_name=f"mapping-candidate-{candidate_index}-smoke",
    )
    case_results = [
        case_result
        for run in experiment.runs
        for scenario_result in run.result.scenario_results
        for subject_result in scenario_result.subject_results
        for case_result in subject_result.case_results
    ]
    runtime_errors = _runtime_error_counts(case_results)
    execution_values = [1.0 if case_result.execution_success else 0.0 for case_result in case_results]
    structural_values = [
        1.0 if case_result.structural_validity else 0.0
        for case_result in case_results
        if case_result.structural_validity is not None
    ]
    required_accuracy_values = [
        case_result.metrics.required_field_accuracy
        for case_result in case_results
    ]
    execution_success_rate = _safe_mean(execution_values)
    structural_validity_rate = (
        _safe_mean(structural_values)
        if structural_values
        else execution_success_rate
    )
    required_field_accuracy = _safe_mean(required_accuracy_values)
    runtime_error_count = sum(runtime_errors.values())
    smoke_score = max(
        0.0,
        round(
            (execution_success_rate * 4.0)
            + (structural_validity_rate * 2.0)
            + (required_field_accuracy * 4.0)
            - (min(runtime_error_count, 100) * 0.01),
            6,
        ),
    )
    report.update(
        {
            "execution_success_rate": execution_success_rate,
            "structural_validity_rate": structural_validity_rate,
            "required_field_accuracy": required_field_accuracy,
            "runtime_error_count": runtime_error_count,
            "runtime_errors": runtime_errors,
            "smoke_score": smoke_score,
            "smoke_passed": bool(case_results) and execution_success_rate > 0.0,
        }
    )
    return report


def _mapping_smoke_score_needs_repair(score: dict[str, Any]) -> bool:
    """Return whether a smoke score has a narrow repair-worthy failure signal."""

    return (
        not bool(score.get("compile_success"))
        or int(score.get("runtime_error_count", 0)) > 0
        or float(score.get("execution_success_rate", 0.0)) < 1.0
        or float(score.get("structural_validity_rate", 0.0)) < 1.0
        or float(score.get("required_field_accuracy", 0.0)) < 1.0
    )


def _repair_runtime_smoke_candidate(
    mapping_ir: MappingIR,
    *,
    candidate_index: int,
    source_schema: SourceSchemaSpec,
    target_schema: TargetSchemaCard,
    smoke_scenarios: Sequence[BenchmarkScenario],
    original_score: dict[str, Any],
    repair_budget_configured: int,
    repair_budget_consumed: int,
) -> tuple[MappingIR, dict[str, Any]]:
    """Apply deterministic repairs to a candidate that failed smoke evidence."""

    structurally_repaired, structural_report = _repair_mapping_candidate(
        mapping_ir,
        source_schema=source_schema,
    )
    repaired_candidate, runtime_rewrites = _apply_runtime_smoke_repairs(
        structurally_repaired,
        target_schema=target_schema,
    )
    rewritten_locations = [
        *structural_report.get("rewritten_references", []),
        *runtime_rewrites,
    ]
    validation = MappingIRValidator().validate(
        repaired_candidate,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    post_repair_score = None
    if validation.valid:
        post_repair_score = _score_mapping_candidate_smoke(
            repaired_candidate,
            candidate_index=candidate_index,
            validation=validation,
            smoke_scenarios=smoke_scenarios,
        )
    repair_applied = bool(
        rewritten_locations
        or structural_report.get("added_source_refs")
        or structural_report.get("added_steps")
    )
    repair_report = {
        "repair_attempted": True,
        "repair_applied": repair_applied,
        "repair_budget": {
            "configured": repair_budget_configured,
            "consumed": repair_budget_consumed,
        },
        "original_error": _mapping_smoke_original_error(original_score),
        "rewritten_locations": rewritten_locations,
        "structural_repair_report": structural_report,
        "post_repair_validation": validation.model_dump(mode="json"),
        "post_repair_smoke_score": post_repair_score,
    }
    return repaired_candidate, repair_report


def _mapping_smoke_original_error(score: dict[str, Any]) -> dict[str, Any]:
    """Build a compact original smoke-failure diagnostic for repair reports."""

    return {
        "compile_error": score.get("compile_error"),
        "runtime_errors": score.get("runtime_errors", {}),
        "execution_success_rate": score.get("execution_success_rate", 0.0),
        "structural_validity_rate": score.get("structural_validity_rate", 0.0),
        "required_field_accuracy": score.get("required_field_accuracy", 0.0),
        "smoke_score": score.get("smoke_score", 0.0),
    }


def _apply_runtime_smoke_repairs(
    mapping_ir: MappingIR,
    *,
    target_schema: TargetSchemaCard,
) -> tuple[MappingIR, list[dict[str, Any]]]:
    """Apply known deterministic repairs for smoke-failed MappingIR programs."""

    repaired, expression_rewrites = _rewrite_expression_helper_aliases(mapping_ir)
    repaired, precondition_rewrites = _remove_status_surface_preconditions(repaired)
    repaired, list_default_rewrites = _default_optional_list_targets(
        repaired,
        target_schema=target_schema,
    )
    return repaired, [
        *expression_rewrites,
        *precondition_rewrites,
        *list_default_rewrites,
    ]


def _rewrite_expression_helper_aliases(mapping_ir: MappingIR) -> tuple[MappingIR, list[dict[str, Any]]]:
    """Rewrite supported fallback helper aliases inside derive expressions."""

    rewrites: list[dict[str, Any]] = []
    rewritten_steps: list[MappingStep] = []
    for step in mapping_ir.steps:
        expression = step.operation.expression
        if step.operation.kind == "derive" and expression is not None:
            rewritten_expression = re.sub(r"\bcoalesce\s*\(", "first_non_null(", expression)
            if rewritten_expression != expression:
                rewrites.append(
                    {
                        "kind": "rewrite_expression_helper",
                        "location": f"steps.{step.id}.operation.expression",
                        "before": expression,
                        "after": rewritten_expression,
                    }
                )
                rewritten_steps.append(
                    step.model_copy(
                        update={
                            "operation": step.operation.model_copy(
                                update={"expression": rewritten_expression}
                            )
                        }
                    )
                )
                continue
        rewritten_steps.append(step)
    if not rewrites:
        return mapping_ir, []
    return mapping_ir.model_copy(update={"steps": rewritten_steps}), rewrites


def _remove_status_surface_preconditions(mapping_ir: MappingIR) -> tuple[MappingIR, list[dict[str, Any]]]:
    """Remove preconditions that over-constrain one source of a status fallback."""

    status_source_refs = _multi_surface_status_source_refs(mapping_ir)
    if not status_source_refs:
        return mapping_ir, []

    rewritten_preconditions: list[ConditionClause] = []
    rewrites: list[dict[str, Any]] = []
    for index, condition in enumerate(mapping_ir.preconditions):
        if condition.ref in status_source_refs:
            rewrites.append(
                {
                    "kind": "remove_status_surface_precondition",
                    "location": f"preconditions[{index}]",
                    "before": condition.model_dump(mode="json"),
                    "after": None,
                }
            )
            continue
        rewritten_preconditions.append(condition)

    if not rewrites:
        return mapping_ir, []
    return mapping_ir.model_copy(update={"preconditions": rewritten_preconditions}), rewrites


def _multi_surface_status_source_refs(mapping_ir: MappingIR) -> set[str]:
    """Return source refs used by a multi-source status derive assignment."""

    step_by_id = {step.id: step for step in mapping_ir.steps}
    status_refs: set[str] = set()
    for assignment in mapping_ir.assignments:
        if assignment.target_path != "status":
            continue
        step = step_by_id.get(assignment.step_id)
        if step is None or step.operation.kind != "derive":
            continue
        source_refs = list(step.operation.source_refs)
        if step.operation.source_ref is not None:
            source_refs.insert(0, step.operation.source_ref)
        if len(source_refs) > 1:
            status_refs.update(source_refs)
    return status_refs


def _default_optional_list_targets(
    mapping_ir: MappingIR,
    *,
    target_schema: TargetSchemaCard,
) -> tuple[MappingIR, list[dict[str, Any]]]:
    """Wrap optional list target copies in a deterministic empty-list default."""

    target_fields = _target_fields_by_path(target_schema)
    source_refs_by_id = {source_ref.id: source_ref for source_ref in mapping_ir.source_refs}
    assignment_count_by_step_id = Counter(assignment.step_id for assignment in mapping_ir.assignments)
    list_default_step_ids = {
        assignment.step_id
        for assignment in mapping_ir.assignments
        if assignment_count_by_step_id[assignment.step_id] == 1
        and _target_field_has_empty_list_default(target_fields.get(assignment.target_path))
    }
    if not list_default_step_ids:
        return mapping_ir, []

    rewrites: list[dict[str, Any]] = []
    rewritten_steps: list[MappingStep] = []
    for step in mapping_ir.steps:
        if step.id not in list_default_step_ids:
            rewritten_steps.append(step)
            continue
        operation = step.operation
        source_ref = operation.source_ref
        if (
            operation.kind not in {"copy", "rename"}
            or source_ref is None
            or source_refs_by_id.get(source_ref) is None
            or source_refs_by_id[source_ref].cardinality != "many"
        ):
            rewritten_steps.append(step)
            continue
        rewritten_operation = StepOperation(
            kind="default",
            source_ref=source_ref,
            value=[],
        )
        rewrites.append(
            {
                "kind": "default_optional_list_target",
                "location": f"steps.{step.id}.operation",
                "before": operation.model_dump(mode="json"),
                "after": rewritten_operation.model_dump(mode="json"),
            }
        )
        rewritten_steps.append(
            step.model_copy(update={"operation": rewritten_operation})
        )
    if not rewrites:
        return mapping_ir, []
    return mapping_ir.model_copy(update={"steps": rewritten_steps}), rewrites


def _target_fields_by_path(target_schema: TargetSchemaCard) -> dict[str, Any]:
    """Index target schema fields recursively by path."""

    fields_by_path: dict[str, Any] = {}

    def visit(field: Any) -> None:
        fields_by_path[field.path] = field
        for child in field.children:
            visit(child)

    for field in target_schema.fields:
        visit(field)
    return fields_by_path


def _target_field_has_empty_list_default(field: Any | None) -> bool:
    """Return whether a target field is an optional list with an empty default."""

    if field is None:
        return False
    return (
        str(field.type_label).startswith("list")
        and field.default in ([], "[]")
    )


def _mapping_smoke_selection_key(score: dict[str, Any], candidate: Any) -> tuple[float, float, float, float, float]:
    """Build a deterministic sort key for smoke-ranked candidates."""

    return (
        float(score["smoke_score"]),
        float(score["execution_success_rate"]),
        float(score["structural_validity_rate"]),
        float(score["required_field_accuracy"]),
        -float(candidate.index),
    )


def _validation_summary(validation: Any) -> dict[str, Any]:
    """Return compact validation details for mapping selection reports."""

    issues = getattr(validation, "issues", [])
    return {
        "valid": bool(getattr(validation, "valid", False)),
        "issue_count": len(issues),
        "issues": [
            issue.model_dump(mode="json") if hasattr(issue, "model_dump") else dict(issue)
            for issue in issues
        ],
    }


def _runtime_error_counts(case_results: Sequence[Any]) -> dict[str, int]:
    """Count per-case runtime errors deterministically."""

    counts: dict[str, int] = {}
    for case_result in case_results:
        if not case_result.error:
            continue
        counts[case_result.error] = counts.get(case_result.error, 0) + 1
    return dict(sorted(counts.items()))


def _copy_benchmark_case(case: BenchmarkCase) -> BenchmarkCase:
    """Deep-copy a benchmark case without sharing mutable payloads."""

    return BenchmarkCase(
        name=case.name,
        record=copy.deepcopy(case.record),
        expected_output=copy.deepcopy(case.expected_output),
        required_fields=list(case.required_fields),
        assertions=copy.deepcopy(case.assertions),
        tags=list(case.tags),
    )


def _build_missing_tags_smoke_case(
    case: BenchmarkCase,
    *,
    source_schema: SourceSchemaSpec,
) -> BenchmarkCase:
    """Create a deterministic missing-tags variant from an existing smoke case."""

    record = copy.deepcopy(case.record)
    for path in _source_paths_for_required_semantic(source_schema, "tags"):
        _remove_record_path(record, path)
    expected_output = copy.deepcopy(case.expected_output)
    expected_output["tags"] = []
    return BenchmarkCase(
        name=f"{case.name}:tags-missing",
        record=record,
        expected_output=expected_output,
        required_fields=list(case.required_fields),
        assertions=copy.deepcopy(case.assertions),
        tags=_dedupe_tags([*case.tags, "smoke:tags_missing"]),
    )


def _source_paths_for_required_semantic(
    source_schema: SourceSchemaSpec,
    semantic: str,
) -> list[str]:
    """Return schema paths matching a required source semantic."""

    return [
        field.path
        for field in source_schema.fields
        if _field_matches_required_semantic(field, semantic)
    ]


def _remove_record_path(record: dict[str, Any], path: str) -> None:
    """Remove one dotted source path from a smoke record when present."""

    clean_segments = [
        segment.replace("[]", "")
        for segment in path.split(".")
        if segment
    ]
    current: Any = record
    for segment in clean_segments[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(segment)
    if isinstance(current, dict) and clean_segments:
        current.pop(clean_segments[-1], None)


def _repair_mapping_candidate(
    program: MappingIR,
    *,
    source_schema: SourceSchemaSpec,
) -> tuple[MappingIR, dict[str, Any]]:
    """Repair narrow source-reference mistakes without changing IR semantics.

    Args:
        program: Parsed mapping candidate returned by the adapter.
        source_schema: Canonical source schema for the current dataset.

    Returns:
        Tuple of repaired program and structured repair report.
    """

    source_refs = list(program.source_refs)
    source_ids = {source_ref.id for source_ref in source_refs}
    source_ref_by_id = {source_ref.id: source_ref for source_ref in source_refs}
    source_ref_by_path = {source_ref.path: source_ref for source_ref in source_refs}
    source_field_by_key: dict[str, Any] = {}
    for field in source_schema.fields:
        for key in [
            field.path,
            field.semantic_name,
            *field.aliases,
            field.path.split(".")[-1],
            _slugify_identifier(field.path),
        ]:
            source_field_by_key.setdefault(key, field)

    rewritten_references: list[dict[str, Any]] = []
    added_source_refs: list[dict[str, Any]] = []
    added_steps: list[dict[str, Any]] = []
    original_steps = list(program.steps)
    existing_step_ids = {step.id for step in original_steps}
    passthrough_step_by_source_ref: dict[str, str] = {}
    appended_steps: list[MappingStep] = []
    assignment_target_paths_by_step_id: dict[str, list[str]] = {}
    for assignment in program.assignments:
        assignment_target_paths_by_step_id.setdefault(assignment.step_id, []).append(
            assignment.target_path
        )
    single_source_step_kinds = {
        "copy",
        "rename",
        "cast",
        "map_enum",
        "unit_convert",
        "split",
        "unnest",
        "validate",
    }

    def _record_rewrite(*, kind: str, location: str, before: str, after: str) -> None:
        """Record one repair rewrite when a reference actually changes.

        Args:
            kind: Rewrite category.
            location: Machine-readable program location.
            before: Original token.
            after: Replacement token.

        Returns:
            None.
        """

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
        """Resolve or synthesize a canonical source reference id.

        Args:
            token: Candidate source reference token.
            location: Machine-readable program location.

        Returns:
            Canonical source reference id when one can be resolved.
        """

        normalized = token.strip()
        if not normalized:
            return None
        for candidate in _candidate_source_tokens(normalized):
            if candidate in source_ref_by_id:
                if normalized != candidate:
                    _record_rewrite(
                        kind="canonicalize_source_ref",
                        location=location,
                        before=normalized,
                        after=candidate,
                    )
                return candidate
            if candidate in source_ref_by_path:
                resolved = source_ref_by_path[candidate].id
                _record_rewrite(
                    kind="canonicalize_source_ref",
                    location=location,
                    before=normalized,
                    after=resolved,
                )
                return resolved
            field = source_field_by_key.get(candidate)
            if field is not None:
                break
        else:
            field = None
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

        new_id = _unique_identifier(
            f"src_{_slugify_identifier(field.path)}",
            used=source_ids,
        )
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
        """Resolve a step reference, creating a copy step for raw source refs.

        Args:
            token: Candidate source or step token.
            location: Machine-readable program location.

        Returns:
            Step id that yields the referenced value.
        """

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

    def _default_value_for_source_ref(source_ref_id: str | None) -> Any:
        """Infer a deterministic default payload for a recovered source ref.

        Args:
            source_ref_id: Optional canonical source reference id.

        Returns:
            Default payload compatible with the recovered source shape.
        """

        if source_ref_id is None:
            return None
        source_ref = source_ref_by_id.get(source_ref_id)
        if source_ref is not None and source_ref.cardinality == "many":
            return []
        return None

    def _ensure_default_step(
        token: str,
        *,
        location: str,
        fallback_target_path: str | None = None,
    ) -> str | None:
        """Resolve a missing ``default_*`` reference into a concrete default step.

        Args:
            token: Candidate default-step token.
            location: Machine-readable program location.
            fallback_target_path: Optional target path used for source inference.

        Returns:
            Concrete step id when a default step can be materialized.
        """

        normalized = token.strip()
        if not normalized:
            return None
        if normalized in existing_step_ids:
            return normalized
        if not normalized.startswith("default_"):
            return None

        inferred_source_ref = None
        for candidate_token in [fallback_target_path, normalized]:
            if candidate_token is None:
                continue
            inferred_source_ref = _ensure_source_ref(
                candidate_token,
                location=f"{location}.operation.source_ref",
            )
            if inferred_source_ref is not None:
                break

        step_id = _unique_identifier(normalized, used=existing_step_ids)
        default_step = MappingStep(
            id=step_id,
            operation=StepOperation(
                kind="default",
                source_ref=inferred_source_ref,
                value=_default_value_for_source_ref(inferred_source_ref),
            ),
            description="Auto-generated default step for a recovered default_* reference.",
        )
        appended_steps.append(default_step)
        existing_step_ids.add(step_id)
        added_steps.append(default_step.model_dump(mode="json"))
        _record_rewrite(
            kind="rewrite_step_reference",
            location=location,
            before=token,
            after=step_id,
        )
        return step_id

    def _resolve_step_reference(
        token: str,
        *,
        location: str,
        fallback_target_path: str | None = None,
    ) -> str | None:
        """Resolve one candidate step reference.

        Args:
            token: Candidate step token.
            location: Machine-readable program location.
            fallback_target_path: Optional target path used for source inference.

        Returns:
            Canonical step id or ``None`` when unresolved.
        """

        normalized = token.strip()
        if not normalized:
            return None
        if normalized in existing_step_ids:
            return normalized
        default_step_id = _ensure_default_step(
            normalized,
            location=location,
            fallback_target_path=fallback_target_path,
        )
        if default_step_id is not None:
            return default_step_id
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
        elif step.operation.kind in single_source_step_kinds:
            for candidate_token in [
                *assignment_target_paths_by_step_id.get(step.id, []),
                step.id,
            ]:
                resolved_source_ref = _ensure_source_ref(
                    candidate_token,
                    location=f"steps.{step.id}.operation.source_ref",
                )
                if resolved_source_ref is not None:
                    break

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
                    fallback_target_path=None,
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
                        fallback_target_path=None,
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
                    fallback_target_path=None,
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
                    fallback_target_path=assignment.target_path,
                )
                or assignment.step_id
            )
        rewritten_assignments.append(
            assignment.model_copy(update={"step_id": resolved_step_id})
        )

    target_path_counts: dict[str, int] = {}
    for assignment in rewritten_assignments:
        target_path_counts[assignment.target_path] = (
            target_path_counts.get(assignment.target_path, 0) + 1
        )
    assignment_step_by_target_path = {
        assignment.target_path: assignment.step_id
        for assignment in rewritten_assignments
        if target_path_counts[assignment.target_path] == 1
    }

    def _resolve_condition_reference(condition: ConditionClause, *, location: str) -> str | None:
        """Resolve one precondition/postcondition reference.

        Args:
            condition: Condition clause being repaired.
            location: Machine-readable condition location.

        Returns:
            Canonical reference token or ``None`` when unresolved.
        """

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
    """Deduplicate a list while preserving the first occurrence order.

    Args:
        values: Candidate values.

    Returns:
        Deduplicated list.
    """

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _slugify_identifier(value: str) -> str:
    """Render a deterministic identifier slug.

    Args:
        value: Arbitrary identifier source.

    Returns:
        Slug safe for generated ids.
    """

    collapsed = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return collapsed or "value"


def _candidate_source_tokens(token: str) -> list[str]:
    """Return progressively normalized source-token candidates.

    Args:
        token: Raw token emitted by a model for a source or copy-like reference.

    Returns:
        Ordered candidate tokens from most specific to most normalized.
    """

    prefixes = (
        "copy_",
        "cast_",
        "default_",
        "src_",
        "source_",
        "field_",
        "input_",
        "value_",
        "mapped_",
        "derive_",
        "derived_",
        "get_",
    )
    suffixes = (
        "_value",
        "_field",
        "_step",
        "_int",
        "_str",
        "_string",
        "_float",
        "_bool",
        "_list",
        "_dict",
    )
    candidates: list[str] = []
    pending = [token.strip()]
    seen: set[str] = set()

    while pending:
        current = pending.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        candidates.append(current)

        for prefix in prefixes:
            if current.startswith(prefix) and len(current) > len(prefix):
                pending.append(current[len(prefix):])

        for suffix in suffixes:
            if current.endswith(suffix) and len(current) > len(suffix):
                pending.append(current[: -len(suffix)])

        if "." in current:
            pending.append(current.split(".")[-1])
        if "_" in current:
            pending.append(current.split("_", 1)[-1])
            pending.append(current.rsplit("_", 1)[0])

    return candidates


def _unique_identifier(base: str, *, used: set[str]) -> str:
    """Return a unique identifier by adding a numeric suffix when needed.

    Args:
        base: Preferred identifier.
        used: Set of ids already in use.

    Returns:
        Unique identifier string.
    """

    if base not in used:
        return base
    suffix = 2
    while f"{base}_{suffix}" in used:
        suffix += 1
    return f"{base}_{suffix}"


def _summarize_benchmark_experiment(experiment: Any) -> dict[str, Any]:
    """Build a compact summary from a repeated benchmark experiment result.

    Args:
        experiment: Repeated benchmark experiment result.

    Returns:
        Machine-readable aggregate metrics for the experiment.
    """

    scenario_rows: list[dict[str, Any]] = []
    all_pass_at_1: list[float] = []
    all_coverage: list[float] = []
    all_macro_accuracy: list[float] = []
    all_required_accuracy: list[float] = []
    for run in experiment.runs:
        for scenario_result in run.result.scenario_results:
            if not scenario_result.subject_results:
                continue
            subject_result = scenario_result.subject_results[0]
            metrics = subject_result.metrics
            scenario_rows.append(
                {
                    "run_id": run.run_id,
                    "scenario_name": scenario_result.scenario_name,
                    "pass_at_1": metrics.pass_at_1,
                    "coverage": metrics.coverage,
                    "macro_field_accuracy": metrics.macro_field_accuracy,
                    "required_field_accuracy": metrics.required_field_accuracy,
                }
            )
            all_pass_at_1.append(metrics.pass_at_1)
            all_coverage.append(metrics.coverage)
            all_macro_accuracy.append(metrics.macro_field_accuracy)
            all_required_accuracy.append(metrics.required_field_accuracy)
    return {
        "run_count": len(experiment.runs),
        "scenario_evaluations": len(scenario_rows),
        "all_scenarios_passed": all(value == 1.0 for value in all_pass_at_1) if all_pass_at_1 else False,
        "mean_pass_at_1": _safe_mean(all_pass_at_1),
        "mean_coverage": _safe_mean(all_coverage),
        "mean_macro_field_accuracy": _safe_mean(all_macro_accuracy),
        "mean_required_field_accuracy": _safe_mean(all_required_accuracy),
        "scenario_rows": scenario_rows,
    }


def _safe_mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean or ``0.0`` for an empty sequence.

    Args:
        values: Numeric values to summarize.

    Returns:
        Mean value or ``0.0`` when the input is empty.
    """

    if not values:
        return 0.0
    return float(mean(values))


def _dedupe_tags(tags: Sequence[str]) -> list[str]:
    """Return deterministic tags without duplicates or empty values.

    Args:
        tags: Candidate tags.

    Returns:
        Deduplicated tag list.
    """

    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _write_json(path: Path, payload: Any) -> None:
    """Write one JSON payload with deterministic formatting.

    Args:
        path: Destination path.
        payload: JSON-compatible payload.

    Returns:
        None.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
