"""Pre-flight checks for verify_commands before agent execution."""

from __future__ import annotations

import subprocess
from typing import Any

from ....logging_config import get_logger
from ....storage.projects import build_project_env
from ..verification_helpers import expand_command

logger = get_logger(__name__)


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
    env = build_project_env(project_id)

    for step in steps:
        step_num = step.get("step_number", 0)
        verify_cmd = step.get("verify_command")

        if not verify_cmd:
            continue

        if step.get("status") == "plan_defect":
            continue

        expanded_cmd = expand_command(verify_cmd)

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
                warnings.append({"step_number": step_num, "warning": msg})
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

    return warnings
