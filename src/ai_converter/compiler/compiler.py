"""Compile validated MappingIR programs into explicit converter-package artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from ai_converter.mapping_ir import MappingIR, MappingIRValidator, MappingStep, StepOperation

from .module_loader import load_module_from_source

CONVERTER_PACKAGE_KIND = "ConverterPackage"
CONVERTER_PACKAGE_VERSION = "1.0"
CONVERTER_PACKAGE_TEST_COMMAND = (
    "python -m pytest tests/unit/compiler tests/unit/validation "
    "tests/integration/converter_pipeline -q -p no:cacheprovider"
)
CONVERTER_PACKAGE_TEST_PATHS = (
    "tests/unit/compiler/test_compiler.py",
    "tests/unit/validation/test_validation.py",
    "tests/integration/converter_pipeline/test_pipeline.py",
)
CONVERTER_PACKAGE_VALIDATION_ENTRY_POINTS = (
    "ai_converter.validation.validate_structural_output",
    "ai_converter.validation.validate_semantic_output",
    "ai_converter.validation.run_acceptance_suite",
    "ai_converter.validation.run_bounded_repair_loop",
)


class CompilationError(ValueError):
    """Raised when a MappingIR program cannot be compiled safely."""


class ConverterPackageManifest(BaseModel):
    """Machine-readable manifest for one compiled converter package artifact.

    Attributes:
        artifact_kind: Stable artifact kind label for the exported package.
        artifact_version: Stable converter-package contract version.
        module_name: Generated module name for the compiled converter.
        converter_entry_point: Converter callable exposed by the generated module.
        program_version: Version of the normalized MappingIR program.
        manifest_file: Relative filename used for the exported manifest.
        module_file: Relative filename used for the exported converter module.
        program_file: Relative filename used for the exported MappingIR payload.
        source_sha256: Stable digest of the generated converter source.
        validation_entry_points: Validation and acceptance entry points for the package.
        test_paths: Focused regression-test paths relevant to the package contract.
        test_command: Focused local regression command for the package surface.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["ConverterPackage"] = CONVERTER_PACKAGE_KIND
    artifact_version: str = CONVERTER_PACKAGE_VERSION
    module_name: str
    converter_entry_point: str = "convert"
    program_version: str
    manifest_file: str = "manifest.json"
    module_file: str
    program_file: str = "mapping_ir.json"
    source_sha256: str
    validation_entry_points: list[str] = Field(
        default_factory=lambda: list(CONVERTER_PACKAGE_VALIDATION_ENTRY_POINTS)
    )
    test_paths: list[str] = Field(default_factory=lambda: list(CONVERTER_PACKAGE_TEST_PATHS))
    test_command: str = CONVERTER_PACKAGE_TEST_COMMAND


@dataclass(slots=True)
class ConverterPackageExport:
    """Filesystem locations written by exporting one converter package.

    Attributes:
        root_dir: Destination directory that contains the exported package files.
        manifest_path: Written manifest path.
        module_path: Written generated converter source path.
        program_path: Written normalized MappingIR payload path.
    """

    root_dir: Path
    manifest_path: Path
    module_path: Path
    program_path: Path


@dataclass(slots=True)
class ConverterPackage:
    """Loaded result of compiling one deterministic MappingIR program.

    Attributes:
        program: Normalized MappingIR program used for code generation.
        module_name: Stable generated module name.
        source_code: Generated Python module source.
        module: Loaded Python module object with the converter entry point.
        manifest: Versioned machine-readable package manifest.
    """

    program: MappingIR
    module_name: str
    source_code: str
    module: ModuleType
    manifest: ConverterPackageManifest

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

    def to_manifest_payload(self) -> dict[str, Any]:
        """Return a stable JSON-compatible manifest payload for the package.

        Args:
            None.

        Returns:
            JSON-compatible package metadata.
        """

        return self.manifest.model_dump(mode="json")

    def export(self, destination: str | Path) -> ConverterPackageExport:
        """Export the package manifest, source module, and MappingIR payload.

        Args:
            destination: Directory that will receive the package files.

        Returns:
            Paths for the written manifest, module, and MappingIR payload.
        """

        root_dir = Path(destination)
        root_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = root_dir / self.manifest.manifest_file
        module_path = root_dir / self.manifest.module_file
        program_path = root_dir / self.manifest.program_file

        module_path.write_text(self.source_code, encoding="utf-8")
        program_path.write_text(
            _json_dumps(self.program.model_dump(mode="json")),
            encoding="utf-8",
        )
        manifest_path.write_text(
            _json_dumps(self.to_manifest_payload()),
            encoding="utf-8",
        )

        return ConverterPackageExport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            module_path=module_path,
            program_path=program_path,
        )


CompiledConverter = ConverterPackage


def compile_mapping_ir(
    program: MappingIR,
    *,
    module_name: str = "generated_converter",
    validate_program: bool = True,
) -> ConverterPackage:
    """Compile one MappingIR program into an importable Python module.

    Args:
        program: MappingIR program to compile.
        module_name: Stable name assigned to the generated module.
        validate_program: Whether to validate the program before compilation.

    Returns:
        Loaded converter package artifact.

    Raises:
        CompilationError: If the program is structurally invalid.
    """

    if validate_program:
        validation = MappingIRValidator().validate(program)
        if not validation.valid:
            messages = "; ".join(f"{issue.location}: {issue.message}" for issue in validation.issues)
            raise CompilationError(f"cannot compile invalid MappingIR: {messages}")
    _raise_for_duplicate_source_ref_ids(program)

    normalized_program = _normalize_program(program)
    source_code = _render_module_source(normalized_program)
    module = load_module_from_source(source_code, module_name)
    return ConverterPackage(
        program=normalized_program,
        module_name=module_name,
        source_code=source_code,
        module=module,
        manifest=ConverterPackageManifest(
            module_name=module_name,
            program_version=normalized_program.version,
            module_file=f"{module_name}.py",
            source_sha256=_source_sha256(source_code),
        ),
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


def _raise_for_duplicate_source_ref_ids(program: MappingIR) -> None:
    """Reject ambiguous source reference ids before code generation.

    Args:
        program: MappingIR program being compiled.

    Raises:
        CompilationError: If any source reference id appears more than once.
    """

    source_ref_counts = Counter(ref.id for ref in program.source_refs)
    duplicate_source_ref_ids = sorted(
        source_ref_id
        for source_ref_id, count in source_ref_counts.items()
        if count > 1
    )
    if duplicate_source_ref_ids:
        duplicate_ids = ", ".join(repr(source_ref_id) for source_ref_id in duplicate_source_ref_ids)
        raise CompilationError(
            "cannot compile MappingIR with duplicate source_ref ids: "
            f"{duplicate_ids}"
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
        "from ai_converter.compiler import runtime_ops",
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
            f"{operation.child_keys[step_ref]!r}: step_values.get({step_ref!r})"
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


def _source_sha256(source_code: str) -> str:
    """Compute the stable digest for generated converter source.

    Args:
        source_code: Generated Python source code.

    Returns:
        SHA-256 hex digest for the source.
    """

    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()


def _json_dumps(payload: dict[str, Any]) -> str:
    """Render one stable JSON document for package export.

    Args:
        payload: JSON-compatible payload to render.

    Returns:
        Stable JSON text with sorted keys.
    """

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
