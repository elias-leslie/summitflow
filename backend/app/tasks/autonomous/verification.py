"""Step verification for autonomous execution.

Handles parsing and executing verification commands with proper output matching.
Supports multiple verification patterns:
- Exit code checks (returncode == 0)
- Output contains checks (expected string in stdout)
- Command aliases (dt -> actual commands)
- Venv path resolution (resolves relative .venv paths to absolute)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)

COMMAND_ALIASES: dict[str, str] = {
    # dt commands run as-is - they have proper TOON output format
    # No expansion needed since dt is in PATH (~/.local/bin/dt)
}


def _resolve_venv_paths(cmd: str, project_id: str) -> str:
    """Resolve .venv paths to absolute paths.

    Args:
        cmd: Command that may contain .venv references
        project_id: Project ID to look up repo path

    Returns:
        Command with absolute venv paths
    """
    if ".venv" not in cmd:
        return cmd

    main_repo = get_project_root_path(project_id)
    if not main_repo:
        return cmd

    main_backend_venv = Path(main_repo) / "backend" / ".venv"
    if not main_backend_venv.exists():
        return cmd

    # Handle both "backend/.venv/bin/" and bare ".venv/bin/" patterns
    # Must check backend/ prefix first to avoid double-replacement
    if "backend/.venv/bin/" in cmd:
        return cmd.replace("backend/.venv/bin/", f"{main_backend_venv}/bin/")
    return cmd.replace(".venv/bin/", f"{main_backend_venv}/bin/")


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

    # Note: "lint:ok", "types:ok", "test:ok" are now checked as output content
    # Previously only checked exit code, which caused false positives when
    # commands failed but pipeline exit code was 0

    if expected_lower.startswith("contains:"):
        return ("contains", expected[9:].strip())

    return ("contains", expected)


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
        return VerificationResult(
            passed=True,
            step_number=step_num,
            output="",
            returncode=0,
            reason="no_verify_command",
        )

    expanded_cmd = expand_command(verify_cmd)
    if project_id:
        expanded_cmd = _resolve_venv_paths(expanded_cmd, project_id)
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

        if passed:
            debug_success(
                f"Step {step_num} verified",
                step=step_num,
                check_type=check_type,
                output_preview=full_output[:100] if full_output else "(empty)",
            )
        else:
            debug_error(
                f"Step {step_num} failed",
                step=step_num,
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
