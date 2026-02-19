"""Step verification for autonomous execution.

Verifies steps by running verify_command and checking exit code (0 = pass).
"""

from __future__ import annotations

import subprocess
from typing import Any

from ...logging_config import get_logger

# Re-export smoke/targeted testing for backward compatibility
from .smoke_testing import SmokeTestResult, TargetedTestResult, run_smoke_tests, run_targeted_tests
from .verification_helpers import (
    VerificationResult,
    _execute_and_check,
    _log_and_build_result,
    _missing_verify_command_result,
    _prepare_verify_command,
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
