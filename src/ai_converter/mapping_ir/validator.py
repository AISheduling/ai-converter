"""Validation helpers for deterministic MappingIR programs."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.schema import SourceSchemaSpec, TargetFieldCard, TargetSchemaCard

from .models import MappingIR, MappingStep, StepOperation

_TARGET_PATH_PATTERN = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")


class ValidationIssue(BaseModel):
    """Machine-readable validation issue for one MappingIR program.

    Attributes:
        code: Stable machine-readable issue code.
        message: Human-readable diagnostic message.
        location: Program location associated with the issue.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    location: str


class ValidationResult(BaseModel):
    """Validation verdict for one MappingIR candidate.

    Attributes:
        valid: Whether the program passed all validation checks.
        issues: Structured validation issues found during validation.
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class MappingIRValidator:
    """Validate MappingIR structure, references, targets, and dependencies."""

    def validate(
        self,
        program: MappingIR,
        *,
        source_schema: SourceSchemaSpec | None = None,
        target_schema: TargetSchemaCard | None = None,
    ) -> ValidationResult:
        """Validate a mapping program against optional source and target contracts.

        Args:
            program: Mapping program to validate.
            source_schema: Optional canonical source schema contract.
            target_schema: Optional canonical target schema card.

        Returns:
            Structured validation verdict for the mapping program.
        """

        issues: list[ValidationIssue] = []
        source_ref_counts = Counter(ref.id for ref in program.source_refs)
        duplicate_source_ref_ids = sorted(
            source_ref_id
            for source_ref_id, count in source_ref_counts.items()
            if count > 1
        )
        source_ids = set(source_ref_counts)
        step_ids = [step.id for step in program.steps]
        step_id_set = set(step_ids)

        for source_ref_id in duplicate_source_ref_ids:
            issues.append(
                ValidationIssue(
                    code="duplicate_source_ref_id",
                    message=f"source refs must have unique ids; repeated id '{source_ref_id}'",
                    location=f"source_refs.{source_ref_id}",
                )
            )

        if len(step_ids) != len(step_id_set):
            issues.append(
                ValidationIssue(
                    code="duplicate_step_id",
                    message="mapping steps must have unique ids",
                    location="steps",
                )
            )

        if source_schema is not None:
            allowed_paths = {field.path for field in source_schema.fields}
            for ref in program.source_refs:
                if ref.path not in allowed_paths:
                    issues.append(
                        ValidationIssue(
                            code="unknown_source_path",
                            message=f"source path '{ref.path}' is not present in the source schema",
                            location=f"source_refs.{ref.id}",
                        )
                    )

        for step in program.steps:
            issues.extend(self._validate_step(step, source_ids=source_ids, step_ids=step_id_set))

        for assignment in program.assignments:
            if assignment.step_id not in step_id_set:
                issues.append(
                    ValidationIssue(
                        code="unknown_step_ref",
                        message=f"assignment references unknown step '{assignment.step_id}'",
                        location=f"assignments.{assignment.target_path}",
                    )
                )
            if target_schema is not None and assignment.target_path not in flatten_target_paths(target_schema):
                issues.append(
                    ValidationIssue(
                        code="unknown_target_path",
                        message=f"target path '{assignment.target_path}' is not part of the target schema",
                        location=f"assignments.{assignment.target_path}",
                    )
                )
            elif target_schema is None and not _TARGET_PATH_PATTERN.match(assignment.target_path):
                issues.append(
                    ValidationIssue(
                        code="invalid_target_path",
                        message=f"target path '{assignment.target_path}' is not a valid dotted path",
                        location=f"assignments.{assignment.target_path}",
                    )
                )

        issues.extend(self._validate_assignment_conflicts(program))
        issues.extend(self._validate_conditions(program, source_ids=source_ids, step_ids=step_id_set))
        issues.extend(self._validate_cycles(program))

        return ValidationResult(valid=not issues, issues=issues)

    def _validate_step(
        self,
        step: MappingStep,
        *,
        source_ids: set[str],
        step_ids: set[str],
    ) -> list[ValidationIssue]:
        """Validate one mapping step.

        Args:
            step: Mapping step to validate.
            source_ids: Known source reference ids from the program.
            step_ids: Known step ids from the program.

        Returns:
            Structured validation issues for the step.
        """

        issues = self._validate_operation_arguments(step.operation, location=f"steps.{step.id}")
        issues.extend(self._validate_operation_expressions(step, location=f"steps.{step.id}"))

        for source_ref in self._source_refs_for_operation(step.operation):
            if source_ref not in source_ids:
                issues.append(
                    ValidationIssue(
                        code="unknown_source_ref",
                        message=f"unknown source ref '{source_ref}'",
                        location=f"steps.{step.id}",
                    )
                )

        for upstream_step in sorted(set(step.depends_on + step.operation.step_refs)):
            if upstream_step == step.id:
                issues.append(
                    ValidationIssue(
                        code="cyclic_dependency",
                        message=f"step '{step.id}' cannot depend on itself",
                        location=f"steps.{step.id}",
                    )
                )
            elif upstream_step not in step_ids:
                issues.append(
                    ValidationIssue(
                        code="unknown_step_ref",
                        message=f"unknown upstream step '{upstream_step}'",
                        location=f"steps.{step.id}",
                    )
                )

        return issues

    @staticmethod
    def _validate_operation_arguments(
        operation: StepOperation,
        *,
        location: str,
    ) -> list[ValidationIssue]:
        """Validate operation-specific arguments for one step.

        Args:
            operation: Step operation payload to validate.
            location: Human-readable program location for diagnostics.

        Returns:
            Structured issues found in the operation arguments.
        """

        issues: list[ValidationIssue] = []
        single_source_ops = {"copy", "rename", "cast", "map_enum", "unit_convert", "split", "unnest", "validate"}
        if operation.kind in single_source_ops and not operation.source_ref:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message=f"operation '{operation.kind}' requires source_ref",
                    location=location,
                )
            )
        if operation.kind == "merge" and not operation.source_refs:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'merge' requires source_refs",
                    location=location,
                )
            )
        if operation.kind == "nest" and not operation.step_refs:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'nest' requires step_refs",
                    location=location,
                )
            )
        if operation.kind == "nest" and not operation.child_keys:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'nest' requires child_keys",
                    location=location,
                )
            )
        if operation.kind == "nest" and operation.child_keys:
            missing_child_keys = [
                step_ref
                for step_ref in operation.step_refs
                if step_ref not in operation.child_keys
            ]
            if missing_child_keys:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message=(
                            "operation 'nest' child_keys must cover every step_ref; missing: "
                            + ", ".join(missing_child_keys)
                        ),
                        location=location,
                    )
                )

            extra_child_keys = sorted(
                step_ref
                for step_ref in operation.child_keys
                if step_ref not in operation.step_refs
            )
            if extra_child_keys:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message=(
                            "operation 'nest' child_keys must reference declared step_refs only; extra: "
                            + ", ".join(extra_child_keys)
                        ),
                        location=location,
                    )
                )

            duplicate_child_keys = sorted(
                child_key
                for child_key, count in Counter(
                    operation.child_keys[step_ref]
                    for step_ref in operation.step_refs
                    if step_ref in operation.child_keys
                ).items()
                if count > 1
            )
            if duplicate_child_keys:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message=(
                            "operation 'nest' child_keys must be unique; duplicates: "
                            + ", ".join(duplicate_child_keys)
                        ),
                        location=location,
                    )
                )
        if operation.kind == "cast" and not operation.to_type:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'cast' requires to_type",
                    location=location,
                )
            )
        if operation.kind == "map_enum" and not operation.mapping:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'map_enum' requires a non-empty mapping",
                    location=location,
                )
            )
        if operation.kind == "unit_convert":
            if operation.factor is None or operation.factor <= 0:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message="operation 'unit_convert' requires a positive factor",
                        location=location,
                    )
                )
            if not operation.from_unit or not operation.to_unit:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message="operation 'unit_convert' requires from_unit and to_unit",
                        location=location,
                    )
                )
        if operation.kind == "split" and not operation.delimiter:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'split' requires delimiter",
                    location=location,
                )
            )
        if operation.kind == "derive" and not operation.expression:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'derive' requires expression",
                    location=location,
                )
            )
        if operation.kind == "default":
            unsupported_arguments = []
            if operation.expression is not None:
                unsupported_arguments.append("expression")
            if operation.source_refs:
                unsupported_arguments.append("source_refs")
            if operation.step_refs:
                unsupported_arguments.append("step_refs")
            if unsupported_arguments:
                issues.append(
                    ValidationIssue(
                        code="invalid_arguments",
                        message=(
                            "operation 'default' does not support "
                            + ", ".join(unsupported_arguments)
                        ),
                        location=location,
                    )
                )
        if operation.kind == "validate" and not operation.predicate:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'validate' requires predicate",
                    location=location,
                )
            )
        if operation.kind == "unnest" and not operation.child_path:
            issues.append(
                ValidationIssue(
                    code="invalid_arguments",
                    message="operation 'unnest' requires child_path",
                    location=location,
                )
            )
        return issues

    @staticmethod
    def _validate_operation_expressions(
        step: MappingStep,
        *,
        location: str,
    ) -> list[ValidationIssue]:
        """Validate operation expressions against the runtime expression contract.

        Args:
            step: Mapping step whose operation may contain an expression.
            location: Human-readable program location for diagnostics.

        Returns:
            Structured issues found in the operation expression or predicate.
        """

        operation = step.operation
        issues: list[ValidationIssue] = []
        if operation.kind == "derive" and operation.expression:
            issues.extend(
                _validate_runtime_expression(
                    operation.expression,
                    allowed_names=_expression_context_names(operation),
                    location=f"{location}.expression",
                )
            )
        if operation.kind == "validate" and operation.predicate:
            issues.extend(
                _validate_runtime_expression(
                    operation.predicate,
                    allowed_names=_expression_context_names(operation) | {"value"},
                    location=f"{location}.predicate",
                )
            )
        return issues

    @staticmethod
    def _validate_assignment_conflicts(program: MappingIR) -> list[ValidationIssue]:
        """Validate conflicting writes across target assignments.

        Args:
            program: Mapping program to inspect.

        Returns:
            Structured conflict issues for duplicate target writes.
        """

        writes: dict[str, list[str]] = defaultdict(list)
        overwrite_flags: dict[str, list[bool]] = defaultdict(list)
        for assignment in program.assignments:
            writes[assignment.target_path].append(assignment.step_id)
            overwrite_flags[assignment.target_path].append(assignment.allow_overwrite)

        issues: list[ValidationIssue] = []
        for target_path, step_ids in writes.items():
            if len(step_ids) > 1 and not all(overwrite_flags[target_path]):
                issues.append(
                    ValidationIssue(
                        code="conflicting_target_write",
                        message=f"multiple steps write to '{target_path}': {', '.join(step_ids)}",
                        location=f"assignments.{target_path}",
                    )
                )
        for target_path in sorted(writes):
            for ancestor_path in _ancestor_target_paths(target_path):
                if ancestor_path not in writes:
                    continue
                combined_step_ids = ", ".join(dict.fromkeys(writes[ancestor_path] + writes[target_path]))
                issues.append(
                    ValidationIssue(
                        code="conflicting_target_write",
                        message=(
                            "hierarchical target paths conflict between "
                            f"'{ancestor_path}' and '{target_path}': {combined_step_ids}"
                        ),
                        location=f"assignments.{target_path}",
                    )
                )
        return issues

    @staticmethod
    def _validate_conditions(
        program: MappingIR,
        *,
        source_ids: set[str],
        step_ids: set[str],
    ) -> list[ValidationIssue]:
        """Validate preconditions and postconditions.

        Args:
            program: Mapping program to inspect.
            source_ids: Known source reference ids from the program.
            step_ids: Known step ids from the program.

        Returns:
            Structured issues for invalid condition references.
        """

        issues: list[ValidationIssue] = []
        for group_name, conditions in (
            ("preconditions", program.preconditions),
            ("postconditions", program.postconditions),
        ):
            for condition in conditions:
                if condition.ref not in source_ids and condition.ref not in step_ids:
                    issues.append(
                        ValidationIssue(
                            code="unknown_reference",
                            message=f"condition references unknown id '{condition.ref}'",
                            location=f"{group_name}.{condition.ref}",
                        )
                    )
        return issues

    @staticmethod
    def _validate_cycles(program: MappingIR) -> list[ValidationIssue]:
        """Validate that step dependencies are acyclic.

        Args:
            program: Mapping program to inspect.

        Returns:
            Structured cycle issues found in the dependency graph.
        """

        dependencies = {
            step.id: sorted(set(step.depends_on + step.operation.step_refs))
            for step in program.steps
        }
        visiting: set[str] = set()
        visited: set[str] = set()
        issues: list[ValidationIssue] = []

        def visit(step_id: str) -> None:
            """Walk one dependency node while tracking active recursion state.

            Args:
                step_id: Step id currently being visited in the dependency graph.
            """

            if step_id in visited or step_id in visiting:
                return
            visiting.add(step_id)
            for neighbor in dependencies.get(step_id, []):
                if neighbor in visiting:
                    issues.append(
                        ValidationIssue(
                            code="cyclic_dependency",
                            message=f"dependency cycle detected between '{step_id}' and '{neighbor}'",
                            location=f"steps.{step_id}",
                        )
                    )
                    continue
                visit(neighbor)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)
        return issues

    @staticmethod
    def _source_refs_for_operation(operation: StepOperation) -> list[str]:
        """Collect source reference ids used by one operation.

        Args:
            operation: Step operation payload to inspect.

        Returns:
            Ordered list of source reference ids used by the operation.
        """

        refs = list(operation.source_refs)
        if operation.source_ref:
            refs.insert(0, operation.source_ref)
        return refs


def flatten_target_paths(
    target_schema: TargetSchemaCard,
    *,
    include_containers: bool = True,
) -> set[str]:
    """Flatten target-card fields into canonical target paths.

    Args:
        target_schema: Target schema card to flatten.
        include_containers: Whether structural container nodes should be
            included in the flattened set.

    Returns:
        Set of canonical dotted target paths.
    """

    paths: set[str] = set()
    for field in target_schema.fields:
        paths.update(_flatten_field_paths(field, include_containers=include_containers))
    return paths


def flatten_assignable_target_paths(target_schema: TargetSchemaCard) -> set[str]:
    """Return only assignable leaf target paths for coverage scoring.

    Container nodes still matter for nested-schema validation and conflict
    analysis, but coverage ratios should reflect leaf assignments rather than
    structural parents.

    Args:
        target_schema: Target schema card to flatten.

    Returns:
        Set of canonical leaf target paths.
    """

    return flatten_target_paths(target_schema, include_containers=False)


def _flatten_field_paths(
    field: TargetFieldCard,
    *,
    include_containers: bool,
) -> set[str]:
    """Flatten one target-card subtree into canonical paths.

    Args:
        field: Target field card to flatten.
        include_containers: Whether to include structural container nodes.

    Returns:
        Set of canonical paths for the subtree.
    """

    paths = {field.path} if include_containers or not field.children else set()
    for child in field.children:
        paths.update(_flatten_field_paths(child, include_containers=include_containers))
    return paths


def _ancestor_target_paths(path: str) -> list[str]:
    """Return dotted ancestor target paths for one canonical target path.

    Args:
        path: Canonical target path to inspect.

    Returns:
        Ordered list of ancestor paths from shallowest to deepest.
    """

    parts = path.split(".")
    return [".".join(parts[:index]) for index in range(1, len(parts))]


def _expression_context_names(operation: StepOperation) -> set[str]:
    """Return runtime variable names exposed to an expression operation.

    Args:
        operation: Operation whose references define runtime variables.

    Returns:
        Set of names available to the restricted expression evaluator.
    """

    names = set(operation.source_refs) | set(operation.step_refs)
    if operation.source_ref is not None:
        names.add(operation.source_ref)
    return names


def _validate_runtime_expression(
    expression: str,
    *,
    allowed_names: set[str],
    location: str,
) -> list[ValidationIssue]:
    """Convert runtime expression validation failures into MappingIR issues.

    Args:
        expression: Restricted expression string.
        allowed_names: Runtime variable names exposed to the expression.
        location: Program location associated with the expression field.

    Returns:
        Empty list when valid, otherwise one structured issue.
    """

    from ai_converter.compiler import runtime_ops

    try:
        runtime_ops.validate_expression(expression, allowed_names)
    except runtime_ops.UnsafeExpressionError as exc:
        return [
            ValidationIssue(
                code="invalid_expression",
                message=str(exc),
                location=location,
            )
        ]
    return []
