"""Compile validated MappingIR programs into importable Python converters."""

from __future__ import annotations

from dataclasses import dataclass
from pprint import pformat
from types import ModuleType
from typing import Any

from ai_converter.mapping_ir import MappingIR, MappingIRValidator, MappingStep, StepOperation

from .module_loader import load_module_from_source


class CompilationError(ValueError):
    """Raised when a MappingIR program cannot be compiled safely."""


@dataclass(slots=True)
class CompiledConverter:
    """Loaded result of compiling one deterministic MappingIR program.

    Attributes:
        program: Normalized MappingIR program used for code generation.
        module_name: Stable generated module name.
        source_code: Generated Python module source.
        module: Loaded Python module object with the converter entry point.
    """

    program: MappingIR
    module_name: str
    source_code: str
    module: ModuleType

    def convert(self, record: dict[str, Any]) -> dict[str, Any]:
        """Execute the generated converter for one source record.

        Args:
            record: One source-side input record.

        Returns:
            A plain target-side dictionary compatible with later validation.
        """

        result = self.module.convert(record)
        if not isinstance(result, dict):
            raise TypeError("compiled converter must return a dictionary payload")
        return result


def compile_mapping_ir(
    program: MappingIR,
    *,
    module_name: str = "generated_converter",
    validate_program: bool = True,
) -> CompiledConverter:
    """Compile one MappingIR program into an importable Python module.

    Args:
        program: MappingIR program to compile.
        module_name: Stable name assigned to the generated module.
        validate_program: Whether to validate the program before compilation.

    Returns:
        Loaded compiled converter artifact.

    Raises:
        CompilationError: If the program is structurally invalid.
    """

    if validate_program:
        validation = MappingIRValidator().validate(program)
        if not validation.valid:
            messages = "; ".join(f"{issue.location}: {issue.message}" for issue in validation.issues)
            raise CompilationError(f"cannot compile invalid MappingIR: {messages}")

    normalized_program = _normalize_program(program)
    source_code = _render_module_source(normalized_program)
    module = load_module_from_source(source_code, module_name)
    return CompiledConverter(
        program=normalized_program,
        module_name=module_name,
        source_code=source_code,
        module=module,
    )


def _normalize_program(program: MappingIR) -> MappingIR:
    """Return a deterministic executable normalization of one MappingIR program.

    Args:
        program: MappingIR program to normalize.

    Returns:
        A MappingIR copy with topologically ordered steps.
    """

    original_steps = list(program.steps)
    index_by_id = {step.id: position for position, step in enumerate(original_steps)}
    remaining = {step.id: _dependencies_for_step(step) for step in original_steps}
    ready = sorted(
        [step.id for step in original_steps if not remaining[step.id]],
        key=lambda step_id: (index_by_id[step_id], step_id),
    )
    ordered_ids: list[str] = []

    while ready:
        current = ready.pop(0)
        ordered_ids.append(current)
        for step_id, dependencies in remaining.items():
            if current in dependencies:
                dependencies.remove(current)
                if not dependencies and step_id not in ordered_ids and step_id not in ready:
                    ready.append(step_id)
        ready.sort(key=lambda step_id: (index_by_id[step_id], step_id))

    if len(ordered_ids) != len(original_steps):
        raise CompilationError("cannot normalize MappingIR with unresolved dependency cycles")

    step_lookup = {step.id: step for step in original_steps}
    return MappingIR(
        version=program.version,
        source_refs=list(program.source_refs),
        steps=[step_lookup[step_id] for step_id in ordered_ids],
        assignments=list(program.assignments),
        preconditions=list(program.preconditions),
        postconditions=list(program.postconditions),
    )


def _dependencies_for_step(step: MappingStep) -> set[str]:
    """Collect the executable dependencies for one MappingIR step.

    Args:
        step: Mapping step to inspect.

    Returns:
        Set of upstream step ids required before the step can run.
    """

    return set(step.depends_on + step.operation.step_refs)


def _render_module_source(program: MappingIR) -> str:
    """Render deterministic Python source for one normalized MappingIR program.

    Args:
        program: Normalized MappingIR program.

    Returns:
        Generated Python module source code.
    """

    lines: list[str] = [
        '"""Generated converter module compiled from deterministic MappingIR."""',
        "",
        "from __future__ import annotations",
        "",
        "from llm_converter.compiler import runtime_ops",
        "",
        f"PROGRAM_VERSION = {program.version!r}",
        "",
        "def convert(record):",
        '    """Convert one source record into a target-side dictionary."""',
        "    source_values = {",
    ]

    for source_ref in program.source_refs:
        lines.append(
            f"        {source_ref.id!r}: runtime_ops.get_path_value(record, {source_ref.path!r}),"
        )
    lines.extend(
        [
            "    }",
            "    step_values = {}",
        ]
    )

    for condition in program.preconditions:
        lines.append(
            "    runtime_ops.check_condition("
            f"{condition.kind!r}, source_values.get({condition.ref!r}), "
            f"expected={_literal(condition.value)}, description={condition.description!r})"
        )

    for step in program.steps:
        lines.append(f"    step_values[{step.id!r}] = {_render_step_expression(step.operation)}")

    for condition in program.postconditions:
        lines.append(
            "    runtime_ops.check_condition("
            f"{condition.kind!r}, step_values.get({condition.ref!r}, source_values.get({condition.ref!r})), "
            f"expected={_literal(condition.value)}, description={condition.description!r})"
        )

    lines.append("    target = {}")
    for assignment in program.assignments:
        lines.append(
            "    runtime_ops.assign_path("
            f"target, {assignment.target_path!r}, step_values[{assignment.step_id!r}], "
            f"allow_overwrite={assignment.allow_overwrite!r})"
        )
    lines.extend(
        [
            "    return target",
            "",
        ]
    )
    return "\n".join(lines)


def _render_step_expression(operation: StepOperation) -> str:
    """Render one runtime expression for a MappingIR step operation.

    Args:
        operation: Step operation payload to render.

    Returns:
        Python expression string for the generated module.
    """

    kind = operation.kind
    if kind in {"copy", "rename"}:
        return f"runtime_ops.copy_value(source_values.get({operation.source_ref!r}))"
    if kind == "cast":
        return (
            "runtime_ops.cast_value("
            f"source_values.get({operation.source_ref!r}), {operation.to_type!r})"
        )
    if kind == "map_enum":
        return (
            "runtime_ops.map_enum_value("
            f"source_values.get({operation.source_ref!r}), {_literal(operation.mapping)})"
        )
    if kind == "unit_convert":
        return (
            "runtime_ops.unit_convert_value("
            f"source_values.get({operation.source_ref!r}), {operation.factor!r}, "
            f"from_unit={operation.from_unit!r}, to_unit={operation.to_unit!r})"
        )
    if kind == "split":
        return (
            "runtime_ops.split_value("
            f"source_values.get({operation.source_ref!r}), {operation.delimiter!r})"
        )
    if kind == "merge":
        values = [
            f"source_values.get({source_ref!r})"
            for source_ref in operation.source_refs
        ] + [
            f"step_values.get({step_ref!r})"
            for step_ref in operation.step_refs
        ]
        return f"runtime_ops.merge_values([{', '.join(values)}], {operation.delimiter!r})"
    if kind == "nest":
        nested_values = ", ".join(
            f"{step_ref!r}: step_values.get({step_ref!r})"
            for step_ref in operation.step_refs
        )
        return f"runtime_ops.nest_values({{{nested_values}}})"
    if kind == "unnest":
        return (
            "runtime_ops.unnest_value("
            f"source_values.get({operation.source_ref!r}), {operation.child_path!r})"
        )
    if kind == "derive":
        return (
            "runtime_ops.derive_value("
            f"{operation.expression!r}, {_render_context_literal(operation)})"
        )
    if kind == "default":
        candidate = (
            f"source_values.get({operation.source_ref!r})"
            if operation.source_ref is not None
            else "None"
        )
        return f"runtime_ops.default_value({candidate}, {_literal(operation.value)})"
    if kind == "drop":
        return "runtime_ops.drop_value()"
    if kind == "validate":
        return (
            "runtime_ops.validate_value("
            f"source_values.get({operation.source_ref!r}), "
            f"{operation.predicate!r}, {_render_context_literal(operation)}, "
            f"message={operation.message!r})"
        )
    raise CompilationError(f"unsupported operation kind during code generation: {kind!r}")


def _render_context_literal(operation: StepOperation) -> str:
    """Render a deterministic runtime context dictionary literal.

    Args:
        operation: Step operation whose references define the context.

    Returns:
        Python dictionary expression string.
    """

    entries: list[str] = []
    if operation.source_ref is not None:
        entries.append(f"{operation.source_ref!r}: source_values.get({operation.source_ref!r})")
    entries.extend(
        f"{source_ref!r}: source_values.get({source_ref!r})"
        for source_ref in operation.source_refs
    )
    entries.extend(
        f"{step_ref!r}: step_values.get({step_ref!r})"
        for step_ref in operation.step_refs
    )
    return "{" + ", ".join(entries) + "}"


def _literal(value: Any) -> str:
    """Render one deterministic Python literal for generated code.

    Args:
        value: Python value to render.

    Returns:
        Stable Python source for the value.
    """

    return pformat(value, sort_dicts=True, width=1000)
