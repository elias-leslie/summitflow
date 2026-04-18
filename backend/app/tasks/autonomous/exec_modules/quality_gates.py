"""Quality gate checking functions."""

from __future__ import annotations

import subprocess

from ....logging_config import get_logger
from ....storage.agent_configs_quality import build_dt_command
from .events import emit_log
from .quality_utils import find_dev_tools

logger = get_logger(__name__)


def _emit_gate_start(task_id: str, cmd: list[str], project_id: str) -> None:
    """Emit a log message indicating quality gate is starting."""
    emit_log(
        task_id,
        "info",
        f"Running final quality gate ({' '.join(cmd)})...",
        source="quality",
        project_id=project_id,
    )


def _emit_gate_result(
    task_id: str, passed: bool, stdout: str, stderr: str, project_id: str
) -> None:
    """Emit a log message with the quality gate pass/fail result."""
    if passed:
        emit_log(
            task_id,
            "info",
            "Final quality gate passed",
            source="quality",
            project_id=project_id,
        )
    else:
        output = (stdout + stderr)[:500]
        emit_log(
            task_id,
            "warn",
            f"Final quality gate failed: {output}",
            source="quality",
            project_id=project_id,
        )


def _run_gate_subprocess(
    task_id: str, cmd: list[str], project_path: str, project_id: str
) -> bool:
    """Run the quality gate subprocess and return pass/fail.

    Returns:
        True if subprocess exits with returncode 0, False on failure or timeout.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        passed = result.returncode == 0
        _emit_gate_result(task_id, passed, result.stdout, result.stderr, project_id)
        return passed
    except subprocess.TimeoutExpired:
        emit_log(
            task_id,
            "warn",
            "Final quality gate timed out",
            source="quality",
            project_id=project_id,
        )
        return False
    except Exception as e:
        emit_log(
            task_id,
            "warn",
            f"Final quality gate error: {e}",
            source="quality",
            project_id=project_id,
        )
        return False


def run_final_quality_gate(
    task_id: str, project_path: str, project_id: str
) -> bool:
    """Run quality gate as final check before AI review.

    Uses per-project quality gate configuration to build the dt command.

    Args:
        task_id: Task ID for logging
        project_path: Path to the project checkout
        project_id: Project ID for logging and config lookup

    Returns:
        True if quality gate passes, False otherwise
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return True

    cmd = build_dt_command(dt_cmd, project_id)
    _emit_gate_start(task_id, cmd, project_id)
    return _run_gate_subprocess(task_id, cmd, project_path, project_id)


def auto_fix_quality(project_path: str, project_id: str) -> bool:
    """Run dt --fix to attempt auto-fixing quality issues.

    Uses per-project config to determine if fix is allowed and which tools to fix.

    Args:
        project_path: Path to the project checkout
        project_id: Project ID for config lookup

    Returns:
        True if dt --fix ran successfully
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return False

    cmd = build_dt_command(dt_cmd, project_id, fix=True)

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except Exception:
        logger.warning("Auto-fix quality gate failed", exc_info=True)
        return False
