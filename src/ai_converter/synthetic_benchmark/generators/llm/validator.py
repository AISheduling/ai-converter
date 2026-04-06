"""Validation gates for LLM-generated synthetic templates."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ai_converter.llm.protocol import LLMResponse
from ai_converter.synthetic_benchmark.generators.deterministic.scenario_sampler import (
    sample_canonical_scenario,
)
from ai_converter.synthetic_benchmark.renderers.l0_renderer import render_l0_payload
from ai_converter.synthetic_benchmark.storage.bundle_store import BundleStore
from ai_converter.synthetic_benchmark.templates import (
    L0TemplateSpec,
    TaskFieldAliases,
    select_shape_variant,
)

from .cache import template_fingerprint
from .models import (
    TemplateGenerationCandidate,
    TemplateGenerationRequest,
    TemplateValidationReport,
    ValidationGateResult,
    ValidationIssue,
)


class TemplateCandidateValidator:
    """Validate parsed template candidates against deterministic repo rules."""

    def build_parse_error_report(
        self,
        response: LLMResponse[TemplateGenerationCandidate],
    ) -> TemplateValidationReport:
        """Build a validation report for one parse-level adapter failure.

        Args:
            response: Structured adapter response that failed to parse.

        Returns:
            Invalid parse-failure report.
        """

        error = response.errors[0] if response.errors else None
        detail = error.message if error is not None else "template candidate did not parse"
        return TemplateValidationReport(
            valid=False,
            gates=[ValidationGateResult(gate="parse", passed=False, detail=detail)],
            issues=[
                ValidationIssue(
                    gate="parse",
                    code=error.code if error is not None else "parse_error",
                    message=detail,
                    location="response",
                )
            ],
        )

    def validate_candidate(
        self,
        candidate: TemplateGenerationCandidate,
        *,
        request: TemplateGenerationRequest,
        accepted_fingerprints: set[str],
    ) -> TemplateValidationReport:
        """Validate one parsed template candidate end to end.

        Args:
            candidate: Parsed candidate returned by the adapter.
            request: Generation request that owns the validation inputs.
            accepted_fingerprints: Structural fingerprints already accepted.

        Returns:
            Machine-readable validation report.
        """

        resolved_template = candidate.resolve(base_template=request.base_template)
        report = TemplateValidationReport(
            valid=False,
            resolved_template=resolved_template,
            gates=[ValidationGateResult(gate="parse", passed=True, detail="candidate parsed as structured output")],
        )

        policy_issues = _policy_issues(resolved_template)
        if policy_issues:
            report.gates.append(
                ValidationGateResult(
                    gate="policy",
                    passed=False,
                    detail="template violates deterministic policy checks",
                )
            )
            report.issues.extend(policy_issues)
            return report

        report.gates.append(
            ValidationGateResult(
                gate="policy",
                passed=True,
                detail="template stays within supported deterministic surface",
            )
        )

        sampled = sample_canonical_scenario(
            request.dry_run_seed,
            request.dry_run_sampler_config,
        )
        try:
            rendered_payload = render_l0_payload(sampled.scenario, resolved_template)
            _validate_rendered_semantics(
                sampled.scenario,
                resolved_template,
                rendered_payload,
            )
        except ValueError as error:
            report.gates.append(
                ValidationGateResult(gate="dry_run", passed=False, detail=str(error))
            )
            report.issues.append(
                ValidationIssue(
                    gate="dry_run",
                    code="dry_run_failed",
                    message=str(error),
                    location="template",
                )
            )
            return report

        report.rendered_payload_preview = rendered_payload
        report.gates.append(
            ValidationGateResult(
                gate="dry_run",
                passed=True,
                detail="template rendered a semantically consistent dry-run payload",
            )
        )

        try:
            _roundtrip_bundle(
                sampled=sampled,
                template=resolved_template,
                dataset_id=request.dataset_id,
            )
        except ValueError as error:
            report.gates.append(
                ValidationGateResult(gate="serialization", passed=False, detail=str(error))
            )
            report.issues.append(
                ValidationIssue(
                    gate="serialization",
                    code="bundle_roundtrip_failed",
                    message=str(error),
                    location="bundle_store",
                )
            )
            return report

        report.gates.append(
            ValidationGateResult(
                gate="serialization",
                passed=True,
                detail="template survives deterministic bundle save/load roundtrip",
            )
        )

        fingerprint = template_fingerprint(resolved_template)
        report.normalized_fingerprint = fingerprint
        if fingerprint in accepted_fingerprints:
            report.gates.append(
                ValidationGateResult(
                    gate="diversity",
                    passed=False,
                    detail="candidate duplicates an already accepted template fingerprint",
                )
            )
            report.issues.append(
                ValidationIssue(
                    gate="diversity",
                    code="duplicate_template",
                    message="candidate duplicates an already accepted template fingerprint",
                    location="template",
                )
            )
            return report

        report.gates.append(
            ValidationGateResult(
                gate="diversity",
                passed=True,
                detail="candidate introduces a new structural fingerprint",
            )
        )
        report.valid = True
        return report

    @staticmethod
    def summarize_failure(report: TemplateValidationReport) -> str:
        """Return one short deterministic failure summary for retry prompts.

        Args:
            report: Validation report produced for one failed attempt.

        Returns:
            Short failure summary string.
        """

        if not report.issues:
            return "candidate failed validation"
        issue = report.issues[0]
        return f"{issue.gate}:{issue.code}: {issue.message}"


def _policy_issues(template: L0TemplateSpec) -> list[ValidationIssue]:
    """Collect deterministic policy issues for one resolved template.

    Args:
        template: Resolved template candidate.

    Returns:
        Policy issues discovered on the template surface.
    """

    issues: list[ValidationIssue] = []
    if template.root_mode == "object" and not template.records_key.strip():
        issues.append(
            ValidationIssue(
                gate="policy",
                code="empty_records_key",
                message="object-mode templates must define a non-empty records_key",
                location="records_key",
            )
        )
    if template.wrap_task_object and not template.task_object_key.strip():
        issues.append(
            ValidationIssue(
                gate="policy",
                code="empty_task_object_key",
                message="wrapped templates must define a non-empty task_object_key",
                location="task_object_key",
            )
        )

    issues.extend(_alias_issues(template.field_aliases, prefix="field_aliases"))
    if template.shape_variant_policy is not None:
        for index, variant in enumerate(template.shape_variant_policy.variants):
            prefix = f"shape_variant_policy.variants[{index}]"
            if variant.wrap_task_object and not (variant.task_object_key or "").strip():
                issues.append(
                    ValidationIssue(
                        gate="policy",
                        code="empty_variant_task_object_key",
                        message="wrapped variants must define a non-empty task_object_key",
                        location=f"{prefix}.task_object_key",
                    )
                )
            if variant.record_envelope_key is not None and not variant.record_envelope_key.strip():
                issues.append(
                    ValidationIssue(
                        gate="policy",
                        code="empty_record_envelope_key",
                        message="record_envelope_key must not be blank when provided",
                        location=f"{prefix}.record_envelope_key",
                    )
                )
            if variant.field_aliases is not None:
                issues.extend(
                    _alias_issues(
                        variant.field_aliases,
                        prefix=f"{prefix}.field_aliases",
                    )
                )
    return issues


def _alias_issues(aliases: TaskFieldAliases, *, prefix: str) -> list[ValidationIssue]:
    """Validate one alias surface for blank or duplicate required fields.

    Args:
        aliases: Alias surface to validate.
        prefix: Location prefix used in emitted issues.

    Returns:
        Alias-related validation issues.
    """

    issues: list[ValidationIssue] = []
    required_aliases = {
        "entity_id": aliases.entity_id,
        "name": aliases.name,
        "status": aliases.status,
        "duration_days": aliases.duration_days,
    }
    for field_name, alias_value in required_aliases.items():
        if not alias_value.strip():
            issues.append(
                ValidationIssue(
                    gate="policy",
                    code="blank_required_alias",
                    message=f"required alias {field_name!r} must not be blank",
                    location=f"{prefix}.{field_name}",
                )
            )
    seen: dict[str, str] = {}
    for field_name, alias_value in required_aliases.items():
        if alias_value in seen:
            issues.append(
                ValidationIssue(
                    gate="policy",
                    code="duplicate_required_alias",
                    message=(
                        f"required alias {field_name!r} duplicates "
                        f"{seen[alias_value]!r}"
                    ),
                    location=f"{prefix}.{field_name}",
                )
            )
        seen[alias_value] = field_name
    return issues


def _validate_rendered_semantics(
    scenario,
    template: L0TemplateSpec,
    payload: dict[str, Any] | list[dict[str, Any]],
) -> None:
    """Verify that dry-run rendering preserves required task semantics.

    Args:
        scenario: Canonical scenario used for the dry run.
        template: Resolved template used for rendering.
        payload: Rendered `L0` payload.

    Raises:
        ValueError: If required structure or required task semantics are lost.
    """

    if template.root_mode == "object":
        if not isinstance(payload, dict):
            raise ValueError("object-mode template must render a dictionary payload")
        records = payload.get(template.records_key)
    else:
        records = payload

    if not isinstance(records, list):
        raise ValueError("rendered payload must contain a list of records")
    if len(records) != len(scenario.tasks):
        raise ValueError("rendered payload record count does not match the canonical scenario")

    for index, task in enumerate(scenario.tasks):
        stable_key = f"{scenario.scenario_id}:{task.entity_id}:{template.template_id}:{index}"
        variant = select_shape_variant(
            template.shape_variant_policy,
            record_index=index,
            stable_key=stable_key,
        )
        aliases = variant.field_aliases if variant and variant.field_aliases is not None else template.field_aliases
        wrap_task_object = (
            variant.wrap_task_object
            if variant and variant.wrap_task_object is not None
            else template.wrap_task_object
        )
        task_object_key = (
            variant.task_object_key
            if variant and variant.task_object_key is not None
            else template.task_object_key
        )
        envelope_key = variant.record_envelope_key if variant is not None else None
        record = records[index]
        if not isinstance(record, dict):
            raise ValueError(f"record {index} is not an object")
        if envelope_key is not None:
            nested = record.get(envelope_key)
            if not isinstance(nested, dict):
                raise ValueError(f"record {index} is missing envelope {envelope_key!r}")
            record = nested
        if wrap_task_object:
            nested = record.get(task_object_key)
            if not isinstance(nested, dict):
                raise ValueError(f"record {index} is missing task wrapper {task_object_key!r}")
            record = nested
        _assert_value(record, aliases.entity_id, task.entity_id, index=index)
        _assert_value(record, aliases.name, task.name, index=index)
        _assert_value(record, aliases.status, task.status, index=index)
        _assert_value(record, aliases.duration_days, task.duration_days, index=index)


def _assert_value(record: dict[str, Any], field_name: str, expected: Any, *, index: int) -> None:
    """Assert one rendered field value inside a dry-run record.

    Args:
        record: Record object to inspect.
        field_name: Expected field name.
        expected: Expected value.
        index: Zero-based record index used in error messages.

    Raises:
        ValueError: If the record is missing the field or value.
    """

    actual = record.get(field_name)
    if actual != expected:
        raise ValueError(
            f"record {index} lost required semantic field {field_name!r}: expected {expected!r}, got {actual!r}"
        )


def _roundtrip_bundle(*, sampled: Any, template: L0TemplateSpec, dataset_id: str) -> None:
    """Round-trip one dry-run bundle through `BundleStore`.

    Args:
        sampled: Deterministic sampled scenario used for the bundle probe.
        template: Template used to build the bundle.
        dataset_id: Dataset identifier forwarded into bundle metadata.

    Raises:
        ValueError: If the bundle cannot be saved and loaded losslessly.
    """

    store = BundleStore()
    bundle = store.build_bundle(
        sampled,
        template,
        dataset_id=dataset_id,
        bundle_id="validation-probe",
        created_at="2026-04-06T00:00:00+00:00",
    )
    temp_root = Path(".pytest-local-tmp") / "synthetic-template-validator"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        export = store.save(bundle, temp_root / "probe")
        loaded = store.load(export.root_dir)
    except Exception as error:  # pragma: no cover - defensive guard
        raise ValueError(str(error)) from error
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    if loaded.model_dump(mode="json") != bundle.model_dump(mode="json"):
        raise ValueError("bundle save/load roundtrip changed the rendered bundle")
