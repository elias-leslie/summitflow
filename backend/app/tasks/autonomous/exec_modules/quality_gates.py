"""Quality gate checking functions."""

from __future__ import annotations

import subprocess

from .events import emit_log
from .quality_utils import find_check_tool


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
        True if subprocess exits with returncode 0, False on failure.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        passed = result.returncode == 0
        _emit_gate_result(task_id, passed, result.stdout, result.stderr, project_id)
        return passed
    except Exception as e:
        emit_log(
            task_id,
            "warn",
            f"Final quality gate error: {e}",
            source="quality",
            project_id=project_id,
        )
        return False


def build_final_quality_gate_command(st_cmd: str, project_id: str) -> list[str]:
    """Build the closeout check for work changed by this task."""
    return [st_cmd, "-P", project_id, "check", "--quick", "--changed-only"]


def run_final_quality_gate(
    task_id: str, project_path: str, project_id: str
) -> bool:
    """Run the task-scoped closeout check.

    Args:
        task_id: Task ID for logging
        project_path: Path to the project checkout.
        project_id: Project ID for logging and command scoping.

    Returns:
        True if quality gate passes, False otherwise
    """
    st_cmd = find_check_tool()
    if not st_cmd:
        return True

    cmd = build_final_quality_gate_command(st_cmd, project_id)
    _emit_gate_start(task_id, cmd, project_id)
    return _run_gate_subprocess(task_id, cmd, project_path, project_id)
