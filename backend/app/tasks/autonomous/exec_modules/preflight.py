"""Pre-flight checks for verify_commands before agent execution."""

from __future__ import annotations

import subprocess
from typing import Any

from ....logging_config import get_logger
from ....storage.projects import build_project_env
from ..verification_helpers import expand_command

logger = get_logger(__name__)


def _should_skip_step(step: dict[str, Any]) -> bool:
    """Return True if the step should be skipped during preflight checks."""
    if not step.get("verify_command"):
        return True
    return step.get("status") == "plan_defect"


def _run_verify_command(
    expanded_cmd: str,
    step_num: int,
    verify_cmd: str,
    project_path: str,
    timeout: int,
    env: dict[str, str],
) -> dict[str, Any] | None:
    """Run a single verify_command and return a warning dict if it exits zero.

    Returns None if the command fails (non-zero exit), times out, or errors.
    """
    try:
        result = subprocess.run(
            expanded_cmd,
            shell=True,
            cwd=project_path,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode == 0:
            msg = (
                f"Step {step_num} verify_command passed BEFORE implementation "
                "— may be tautological. Verify it tests actual changes."
            )
            logger.warning(
                "preflight_tautological",
                step_number=step_num,
                verify_command=verify_cmd[:80],
            )
            return {"step_number": step_num, "warning": msg}
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        logger.debug("Preflight verify_command check failed for step %s", step_num, exc_info=True)
    return None


def check_verify_commands_red(
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str | None = None,
    timeout: int = 5,
) -> list[dict[str, Any]]:
    """Run each verify_command BEFORE implementation to check for tautological commands.

    A verify_command that passes before any code changes may be tautological —
    it doesn't actually test the implementation.

    This is warning-only, never blocking. Some commands legitimately pass
    before implementation (e.g., test -f package.json for an existing file).

    Returns:
        List of dicts with step_number and warning message for tautological steps.
    """
    warnings: list[dict[str, Any]] = []
    env = build_project_env(project_id, working_dir=project_path)

    for step in steps:
        if _should_skip_step(step):
            continue
        step_num = step.get("step_number", 0)
        verify_cmd = step["verify_command"]
        warning = _run_verify_command(
            expand_command(verify_cmd), step_num, verify_cmd, project_path, timeout, env
        )
        if warning is not None:
            warnings.append(warning)

    return warnings
