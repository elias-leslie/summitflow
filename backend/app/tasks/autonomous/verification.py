"""Step verification for autonomous execution.

Verifies steps by running verify_command and checking exit code (0 = pass).
Supports:
- Command aliases (dt -> actual commands)
- Project environment resolution (venv from main repo for worktrees)
- Smoke tests for changed Python files (import + __all__ checks)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import build_project_env

# Re-export smoke/targeted testing for backward compatibility
from .smoke_testing import SmokeTestResult, TargetedTestResult, run_smoke_tests, run_targeted_tests
from .verification_helpers import (
    adjust_command_for_cwd,
    expand_command,
    resolve_working_directory,
)

logger = get_logger(__name__)

# Public API exports
__all__ = [
    "SmokeTestResult",
    "TargetedTestResult",
    "VerificationResult",
    "run_smoke_tests",
    "run_targeted_tests",
    "verify_step",
]


@dataclass
class VerificationResult:
    """Result of a step verification."""

    passed: bool
    step_number: int
    output: str
    returncode: int
    reason: str


def _execute_and_check(
    command: str,
    working_dir: str,
    timeout: int,
    env: dict[str, str],
) -> tuple[bool, str, str, int]:
    """Execute command and check exit code.

    Returns:
        Tuple of (passed, reason, output, returncode)
    """
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=working_dir,
        env=env,
    )

    output = result.stdout.strip()
    stderr = result.stderr.strip()
    full_output = f"{output}\n{stderr}".strip() if stderr else output

    passed = result.returncode == 0
    reason = "exit_code_0" if passed else f"exit_code_{result.returncode}"

    return passed, reason, full_output, result.returncode


def _missing_verify_command_result(step_num: int) -> VerificationResult:
    """Return a failed result for steps with no verify_command."""
    logger.warning(
        "Step has no verify_command — cannot pass without verification",
        step_num=step_num,
    )
    return VerificationResult(
        passed=False,
        step_number=step_num,
        output="Step has no verify_command. Every step must have verification.",
        returncode=-1,
        reason="missing_verify_command",
    )


def _prepare_verify_command(
    verify_cmd: str,
    working_dir: str,
    timeout: int,
    project_id: str | None,
) -> tuple[str, str, dict[str, str], int]:
    """Expand command, resolve cwd, build env, and adjust timeout.

    Returns:
        Tuple of (expanded_cmd, effective_cwd, env, adjusted_timeout)
    """
    expanded_cmd = expand_command(verify_cmd)
    env = build_project_env(project_id, working_dir=working_dir)

    if any(cmd in expanded_cmd for cmd in ["dt ", "commit.sh", "npm run build"]):
        timeout = max(timeout, 300)

    effective_cwd = resolve_working_directory(working_dir, expanded_cmd)
    expanded_cmd = adjust_command_for_cwd(expanded_cmd, working_dir, effective_cwd)
    return expanded_cmd, effective_cwd, env, timeout


def _log_and_build_result(
    step_num: int,
    passed: bool,
    reason: str,
    full_output: str,
    returncode: int,
) -> VerificationResult:
    """Log verification outcome and return a VerificationResult."""
    logger.info(
        "Step verification result",
        step_num=step_num,
        passed=passed,
        returncode=returncode,
        reason=reason,
        output_preview=full_output[:200] if full_output else "(empty)",
    )
    debug_fn = debug_success if passed else debug_error
    debug_fn(
        f"Step {step_num} {'verified' if passed else 'failed'}",
        step=step_num,
        reason=reason if not passed else None,
        output_preview=full_output[:200] if full_output else "(empty)",
    )
    return VerificationResult(
        passed=passed,
        step_number=step_num,
        output=full_output[:1000],
        returncode=returncode,
        reason=reason,
    )


def verify_step(
    step: dict[str, Any],
    working_dir: str,
    timeout: int = 60,
    project_id: str | None = None,
) -> VerificationResult:
    """Verify a single step by running verify_command and checking exit code.

    Args:
        step: Step dict with verify_command
        working_dir: Directory to run command in
        timeout: Command timeout in seconds
        project_id: Project ID for resolving venv paths

    Returns:
        VerificationResult with pass/fail status
    """
    step_num = step.get("step_number", 0)
    verify_cmd = step.get("verify_command")

    if not verify_cmd:
        return _missing_verify_command_result(step_num)

    expanded_cmd, effective_cwd, env, timeout = _prepare_verify_command(
        verify_cmd, working_dir, timeout, project_id
    )

    logger.info(
        "Verifying step",
        step_num=step_num,
        original_cmd=verify_cmd[:80],
        expanded_cmd=expanded_cmd[:80] if expanded_cmd != verify_cmd else None,
        cwd=effective_cwd,
    )

    try:
        passed, reason, full_output, returncode = _execute_and_check(
            expanded_cmd, effective_cwd, timeout, env
        )
        return _log_and_build_result(step_num, passed, reason, full_output, returncode)

    except subprocess.TimeoutExpired:
        logger.warning("Step verification timed out", step_num=step_num, timeout=timeout)
        return VerificationResult(
            passed=False, step_number=step_num, output="", returncode=-1, reason="timeout"
        )
    except Exception as e:
        logger.warning("Step verification error", step_num=step_num, error=str(e))
        return VerificationResult(
            passed=False, step_number=step_num, output="", returncode=-1, reason=f"error: {e}"
        )
