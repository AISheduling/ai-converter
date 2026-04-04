"""Bounded repair-loop orchestration for compiled MappingIR converters."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from llm_converter.compiler import CompilationError, compile_mapping_ir
from llm_converter.mapping_ir import MappingIR

from .acceptance import AcceptanceCase, AcceptanceReport, run_acceptance_suite


class FailureBundle(BaseModel):
    """Machine-readable failure bundle passed to a repair strategy."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    program: dict
    acceptance_report: AcceptanceReport


class RepairLoopResult(BaseModel):
    """Result of running a bounded repair loop."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    iterations_used: int
    final_program: MappingIR
    final_report: AcceptanceReport
    history: list[AcceptanceReport] = Field(default_factory=list)


class RepairStrategy(Protocol):
    """Interface used by the bounded repair loop to obtain patched programs."""

    def propose_patch(self, program: MappingIR, failure_bundle: FailureBundle) -> MappingIR | None:
        """Propose a patched MappingIR program after one failed acceptance run.

        Args:
            program: Current MappingIR program that just failed.
            failure_bundle: Machine-readable failure context for the attempt.

        Returns:
            A patched or replacement MappingIR program, or ``None`` to stop.
        """


def run_bounded_repair_loop(
    program: MappingIR,
    dataset: list[AcceptanceCase],
    target_model: type[BaseModel],
    repair_strategy: RepairStrategy,
    *,
    max_repair_iterations: int = 1,
    module_name_prefix: str = "generated_converter",
) -> RepairLoopResult:
    """Run the bounded repair loop for one MappingIR program.

    Args:
        program: Initial MappingIR program to compile and validate.
        dataset: Acceptance fixture dataset.
        target_model: Pydantic target model used for structural validation.
        repair_strategy: Strategy that returns patched MappingIR programs.
        max_repair_iterations: Maximum number of repair attempts after the initial run.
        module_name_prefix: Stable prefix for generated module names.

    Returns:
        Repair-loop result with the final report and history.
    """

    current_program = program
    history: list[AcceptanceReport] = []

    for attempt in range(max_repair_iterations + 1):
        report = _run_compiled_acceptance(
            current_program,
            dataset,
            target_model,
            attempt=attempt,
            module_name=f"{module_name_prefix}_{attempt}",
        )
        history.append(report)

        if report.execution_success and report.structural_validity and report.semantic_validity:
            return RepairLoopResult(
                success=True,
                iterations_used=attempt,
                final_program=current_program,
                final_report=report,
                history=history,
            )

        if attempt >= max_repair_iterations:
            break

        patched = repair_strategy.propose_patch(
            current_program,
            FailureBundle(
                attempt=attempt,
                program=current_program.model_dump(mode="json"),
                acceptance_report=report,
            ),
        )
        if patched is None:
            break
        current_program = patched

    final_report = history[-1]
    return RepairLoopResult(
        success=False,
        iterations_used=len(history) - 1,
        final_program=current_program,
        final_report=final_report,
        history=history,
    )


def _run_compiled_acceptance(
    program: MappingIR,
    dataset: list[AcceptanceCase],
    target_model: type[BaseModel],
    *,
    attempt: int,
    module_name: str,
) -> AcceptanceReport:
    """Compile one program and execute the acceptance suite for it.

    Args:
        program: MappingIR program to compile.
        dataset: Acceptance fixture dataset.
        target_model: Pydantic target model used for structural validation.
        attempt: Current repair-loop attempt number.
        module_name: Generated module name for this attempt.

    Returns:
        Acceptance report for the compiled program.
    """

    try:
        compiled = compile_mapping_ir(program, module_name=module_name)
    except CompilationError as exc:
        return AcceptanceReport(
            execution_success=False,
            structural_validity=False,
            semantic_validity=False,
            coverage=0.0,
            repair_iterations=attempt,
            compiler_error=str(exc),
        )

    report = run_acceptance_suite(
        compiled.convert,
        dataset,
        target_model,
        repair_iterations=attempt,
    )
    return report
