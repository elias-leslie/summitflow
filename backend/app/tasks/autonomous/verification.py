"""Step verification for autonomous execution.

Handles parsing and executing verification commands with proper output matching.
Supports multiple verification patterns:
- Exit code checks (returncode == 0)
- Output contains checks (expected string in stdout)
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

# Re-export smoke testing for backward compatibility
from .smoke_testing import SmokeTestResult, run_smoke_tests
from .verification_helpers import (
    adjust_command_for_cwd,
    expand_command,
    parse_expected,
    resolve_working_directory,
)

logger = get_logger(__name__)

# Public API exports
__all__ = ["SmokeTestResult", "VerificationResult", "run_smoke_tests", "verify_step"]


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
    check_type: str,
    check_value: str | None,
) -> tuple[bool, str, str, int]:
    """Execute command and check result.

    Returns:
        Tuple of (passed, reason, output, returncode)
    """
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=working_dir,
        env=env,
    )

    output = result.stdout.strip()
    stderr = result.stderr.strip()
    full_output = f"{output}\n{stderr}".strip() if stderr else output

    # Check verification result
    if check_type == "exit_code":
        passed = result.returncode == 0
        reason = "exit_code_0" if passed else f"exit_code_{result.returncode}"
    elif check_type == "contains":
        passed = check_value in full_output if check_value else True
        reason = "contains_match" if passed else "contains_not_found"
    else:
        passed = result.returncode == 0
        reason = "default_exit_code"

    return passed, reason, full_output, result.returncode


def verify_step(
    step: dict[str, Any],
    working_dir: str,
    timeout: int = 60,
    project_id: str | None = None,
) -> VerificationResult:
    """Verify a single step.

    Args:
        step: Step dict with verify_command and expected_output
        working_dir: Directory to run command in
        timeout: Command timeout in seconds
        project_id: Project ID for resolving venv paths

    Returns:
        VerificationResult with pass/fail status
    """
    step_num = step.get("step_number", 0)
    verify_cmd = step.get("verify_command")
    expected = step.get("expected_output", "")

    if not verify_cmd:
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

    expanded_cmd = expand_command(verify_cmd)
    check_type, check_value = parse_expected(expected)
    env = build_project_env(project_id)

    # Increase timeout for long-running commands
    if any(cmd in expanded_cmd for cmd in ["dt ", "commit.sh", "npm run build"]):
        timeout = max(timeout, 300)

    # Resolve effective working directory
    effective_cwd = resolve_working_directory(working_dir, expanded_cmd)
    expanded_cmd = adjust_command_for_cwd(expanded_cmd, working_dir, effective_cwd)

    logger.info(
        "Verifying step",
        step_num=step_num,
        original_cmd=verify_cmd[:80],
        expanded_cmd=expanded_cmd[:80] if expanded_cmd != verify_cmd else None,
        check_type=check_type,
        check_value=check_value[:50] if check_value else None,
        cwd=effective_cwd,
    )

    try:
        passed, reason, full_output, returncode = _execute_and_check(
            expanded_cmd, effective_cwd, timeout, env, check_type, check_value
        )

        # Log result
        logger.info(
            "Step verification result",
            step_num=step_num,
            passed=passed,
            returncode=returncode,
            check_type=check_type,
            reason=reason,
            output_preview=full_output[:200] if full_output else "(empty)",
        )

        debug_fn = debug_success if passed else debug_error
        debug_fn(
            f"Step {step_num} {'verified' if passed else 'failed'}",
            step=step_num,
            check_type=check_type,
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

    except subprocess.TimeoutExpired:
        logger.warning("Step verification timed out", step_num=step_num, timeout=timeout)
        return VerificationResult(
            passed=False,
            step_number=step_num,
            output="",
            returncode=-1,
            reason="timeout",
        )
    except Exception as e:
        logger.warning("Step verification error", step_num=step_num, error=str(e))
        return VerificationResult(
            passed=False,
            step_number=step_num,
            output="",
            returncode=-1,
            reason=f"error: {e}",
        )
