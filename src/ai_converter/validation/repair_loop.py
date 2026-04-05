"""Bounded repair-loop orchestration for compiled MappingIR converters."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ai_converter.compiler import CompilationError, compile_mapping_ir
from ai_converter.mapping_ir import MappingIR

from .acceptance import AcceptanceCase, AcceptanceReport, run_acceptance_suite

TRACE_ARTIFACT_VERSION = "1.0"
RepairLoopDecision = Literal["accepted", "patched", "strategy_declined", "max_iterations_reached"]


class FailureBundle(BaseModel):
    """Machine-readable failure bundle passed to a repair strategy."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    program: dict[str, Any]
    acceptance_report: AcceptanceReport

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic export payload for one repair failure.

        Returns:
            JSON-compatible failure bundle for caller-managed persistence.
        """

        payload = self.model_dump(mode="json")
        payload["acceptance_report"] = self.acceptance_report.to_dict()
        return payload

    def to_trace_artifact(self) -> dict[str, Any]:
        """Return one stable JSON-compatible failure artifact.

        Returns:
            Dictionary suitable for offline persistence and later audit.
        """

        return {
            "artifact_kind": "repair_failure_bundle",
            "artifact_version": TRACE_ARTIFACT_VERSION,
            **self.model_dump(mode="json"),
        }


class RepairAttemptTrace(BaseModel):
    """Machine-readable audit record for one repair-loop attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    program: dict[str, Any]
    acceptance_report: AcceptanceReport
    decision: RepairLoopDecision
    failure_bundle: FailureBundle | None = None
    patched_program: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic export payload for one repair attempt.

        Returns:
            JSON-compatible attempt trace with failure and patch context.
        """

        payload = self.model_dump(mode="json")
        payload["acceptance_report"] = self.acceptance_report.to_dict()
        payload["failure_bundle"] = self.failure_bundle.to_dict() if self.failure_bundle is not None else None
        return payload

    def to_trace_artifact(self) -> dict[str, Any]:
        """Return one stable JSON-compatible attempt artifact.

        Returns:
            Dictionary suitable for offline persistence and later audit.
        """

        return {
            "artifact_kind": "repair_attempt_trace",
            "artifact_version": TRACE_ARTIFACT_VERSION,
            **self.model_dump(mode="json"),
        }


class RepairLoopResult(BaseModel):
    """Result of running a bounded repair loop."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    iterations_used: int
    final_program: MappingIR
    final_report: AcceptanceReport
    final_decision: RepairLoopDecision
    history: list[AcceptanceReport] = Field(default_factory=list)
    attempt_traces: list[RepairAttemptTrace] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic export payload for one repair-loop run.

        Returns:
            JSON-compatible repair trace with final outcome and attempts.
        """

        payload = self.model_dump(mode="json")
        payload["final_program"] = self.final_program.model_dump(mode="json")
        payload["final_report"] = self.final_report.to_dict()
        payload["history"] = [report.to_dict() for report in self.history]
        payload["attempt_traces"] = [trace.to_dict() for trace in self.attempt_traces]
        return payload

    def to_trace_artifact(self) -> dict[str, Any]:
        """Return one stable JSON-compatible repair-loop artifact.

        Returns:
            Dictionary containing the final outcome and per-attempt traces.
        """

        return {
            "artifact_kind": "repair_loop_trace",
            "artifact_version": TRACE_ARTIFACT_VERSION,
            **self.model_dump(mode="json"),
        }


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
    attempt_traces: list[RepairAttemptTrace] = []

    for attempt in range(max_repair_iterations + 1):
        report = _run_compiled_acceptance(
            current_program,
            dataset,
            target_model,
            attempt=attempt,
            module_name=f"{module_name_prefix}_{attempt}",
        )
        history.append(report)
        program_payload = current_program.model_dump(mode="json")

        if report.execution_success and report.structural_validity and report.semantic_validity:
            attempt_traces.append(
                RepairAttemptTrace(
                    attempt=attempt,
                    program=program_payload,
                    acceptance_report=report,
                    decision="accepted",
                )
            )
            return RepairLoopResult(
                success=True,
                iterations_used=attempt,
                final_program=current_program,
                final_report=report,
                final_decision="accepted",
                history=history,
                attempt_traces=attempt_traces,
            )

        failure_bundle = FailureBundle(
            attempt=attempt,
            program=program_payload,
            acceptance_report=report,
        )

        if attempt >= max_repair_iterations:
            attempt_traces.append(
                RepairAttemptTrace(
                    attempt=attempt,
                    program=program_payload,
                    acceptance_report=report,
                    decision="max_iterations_reached",
                    failure_bundle=failure_bundle,
                )
            )
            break

        patched = repair_strategy.propose_patch(current_program, failure_bundle)
        if patched is None:
            attempt_traces.append(
                RepairAttemptTrace(
                    attempt=attempt,
                    program=program_payload,
                    acceptance_report=report,
                    decision="strategy_declined",
                    failure_bundle=failure_bundle,
                )
            )
            break

        attempt_traces.append(
            RepairAttemptTrace(
                attempt=attempt,
                program=program_payload,
                acceptance_report=report,
                decision="patched",
                failure_bundle=failure_bundle,
                patched_program=patched.model_dump(mode="json"),
            )
        )
        current_program = patched

    final_report = history[-1]
    return RepairLoopResult(
        success=False,
        iterations_used=len(history) - 1,
        final_program=current_program,
        final_report=final_report,
        final_decision=attempt_traces[-1].decision,
        history=history,
        attempt_traces=attempt_traces,
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
