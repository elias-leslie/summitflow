"""Exception classes for steps module."""

from __future__ import annotations

from typing import Any


class StepGateError(Exception):
    """Raised when step completion gate is violated."""

    def __init__(self, message: str, missing_steps: list[int] | None = None):
        super().__init__(message)
        self.missing_steps = missing_steps or []


class StepVerificationError(Exception):
    """Raised when step completion is blocked by failed quality check.

    Attributes:
        step_number: The step that failed
        output: The command output
        exit_code: The exit code
        cwd: The working directory used for execution
        next_steps: Guidance for what to do next
    """

    NEXT_STEPS_GUIDANCE = """
Next steps:
  1. Fix your implementation to match the expected behavior
  2. If the plan is wrong: st step defect <subtask-id> <step#>
     (creates fix step, marks defect — all in one command)"""

    def __init__(
        self,
        message: str,
        step_number: int,
        output: str,
        exit_code: int = 1,
        cwd: str | None = None,
    ):
        full_message = f"{message}\n{self.NEXT_STEPS_GUIDANCE}"
        super().__init__(full_message)
        self.step_number = step_number
        self.output = output
        self.exit_code = exit_code
        self.cwd = cwd
        self.next_steps = self.NEXT_STEPS_GUIDANCE


class PlanDefectError(Exception):
    """Raised when a plan_defect operation is invalid."""

    pass


class StepDeletionResult:
    """Result of step deletion with audit info."""

    def __init__(
        self,
        deleted: bool,
        was_passed: bool = False,
        subtask_invalidated: bool = False,
        step_details: dict[str, Any] | None = None,
    ):
        self.deleted = deleted
        self.was_passed = was_passed
        self.subtask_invalidated = subtask_invalidated
        self.step_details = step_details
