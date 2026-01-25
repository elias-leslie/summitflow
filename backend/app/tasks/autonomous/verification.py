"""Step verification for autonomous execution.

Handles parsing and executing verification commands with proper output matching.
Supports multiple verification patterns:
- Exit code checks (returncode == 0)
- Output contains checks (expected string in stdout)
- Command aliases (dt -> actual commands)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

COMMAND_ALIASES: dict[str, str] = {
    "dt ruff": "cd backend && .venv/bin/ruff check app/",
    "dt mypy": "cd backend && .venv/bin/mypy app/ --ignore-missing-imports",
    "dt pytest": "cd backend && .venv/bin/pytest -x -q",
}


@dataclass
class VerificationResult:
    """Result of a step verification."""

    passed: bool
    step_number: int
    output: str
    returncode: int
    reason: str


def expand_command(cmd: str) -> str:
    """Expand command aliases to full commands."""
    for alias, expansion in COMMAND_ALIASES.items():
        if cmd.strip().startswith(alias):
            remainder = cmd.strip()[len(alias) :].strip()
            return f"{expansion} {remainder}".strip()
    return cmd


def parse_expected(expected: str | None) -> tuple[str, str | None]:
    """Parse expected_output into (check_type, value).

    Returns:
        (check_type, value) where check_type is one of:
        - "exit_code": Check returncode == 0
        - "contains": Check value in output
        - "exact": Check output == value
    """
    if not expected:
        return ("exit_code", None)

    expected_lower = expected.lower().strip()

    if expected_lower.startswith("exit code"):
        return ("exit_code", None)

    if expected_lower in ("lint:ok", "types:ok", "test:ok"):
        return ("exit_code", None)

    if expected_lower.startswith("contains:"):
        return ("contains", expected[9:].strip())

    return ("contains", expected)


def verify_step(
    step: dict[str, Any],
    working_dir: str,
    timeout: int = 60,
) -> VerificationResult:
    """Verify a single step.

    Args:
        step: Step dict with verify_command and expected_output
        working_dir: Directory to run command in
        timeout: Command timeout in seconds

    Returns:
        VerificationResult with pass/fail status
    """
    step_num = step.get("step_number", 0)
    verify_cmd = step.get("verify_command")
    expected = step.get("expected_output", "")

    if not verify_cmd:
        return VerificationResult(
            passed=True,
            step_number=step_num,
            output="",
            returncode=0,
            reason="no_verify_command",
        )

    expanded_cmd = expand_command(verify_cmd)
    check_type, check_value = parse_expected(expected)

    logger.info(
        "Verifying step",
        step_num=step_num,
        original_cmd=verify_cmd[:80],
        expanded_cmd=expanded_cmd[:80] if expanded_cmd != verify_cmd else None,
        check_type=check_type,
        check_value=check_value[:50] if check_value else None,
        cwd=working_dir,
    )

    try:
        result = subprocess.run(
            expanded_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )

        output = result.stdout.strip()
        stderr = result.stderr.strip()
        full_output = f"{output}\n{stderr}".strip() if stderr else output

        if check_type == "exit_code":
            passed = result.returncode == 0
            reason = "exit_code_0" if passed else f"exit_code_{result.returncode}"
        elif check_type == "contains":
            passed = check_value in full_output if check_value else True
            reason = "contains_match" if passed else "contains_not_found"
        else:
            passed = result.returncode == 0
            reason = "default_exit_code"

        logger.info(
            "Step verification result",
            step_num=step_num,
            passed=passed,
            returncode=result.returncode,
            check_type=check_type,
            reason=reason,
            output_preview=full_output[:200] if full_output else "(empty)",
        )

        return VerificationResult(
            passed=passed,
            step_number=step_num,
            output=full_output[:1000],
            returncode=result.returncode,
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
