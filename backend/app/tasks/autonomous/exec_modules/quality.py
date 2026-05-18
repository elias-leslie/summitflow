"""Quality gate execution and final-gate command building."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.storage.agent_configs_quality import build_st_check_command

from .ah_events import emit_quality_gate_result
from .events import emit_log
from .quality_utils import find_check_tool

_TASK_SCOPED_MODES = {"--quick", "-q", "--check", "-c", "--frontend-only", "--fe"}


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
        env = _task_scoped_env(project_path)
        result = subprocess.run(
            cmd,
            cwd=project_path,
            env=env,
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


def _task_changed_files(project_path: str) -> list[str]:
    root = Path(project_path)
    merge_base = subprocess.run(
        ["git", "merge-base", "main", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return []

    diff = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRTUXB",
            merge_base.stdout.strip(),
            "HEAD",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        return []
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def _task_scoped_env(project_path: str) -> dict[str, str]:
    env = os.environ.copy()
    changed_files = _task_changed_files(project_path)
    if changed_files:
        env["ST_CHECK_CHANGED_FILES"] = "\n".join(changed_files)
    return env


def build_final_quality_gate_command(st_cmd: str, project_id: str) -> list[str]:
    """Build the configured check as a task-scoped pre-merge gate."""
    cmd = build_st_check_command(st_cmd, project_id)
    scoped_cmd = [cmd[0], "-P", project_id, *cmd[1:]]
    if not {"--changed-only", "-d"}.intersection(scoped_cmd) and any(
        mode in scoped_cmd for mode in _TASK_SCOPED_MODES
    ):
        scoped_cmd.append("--changed-only")
    return scoped_cmd


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


def run_quality_gate(
    task_id: str,
    project_path: str,
    project_id: str,
) -> bool:
    """Run the final task-scoped quality gate and emit its result event.

    Args:
        task_id: The task ID
        project_path: Path to project directory
        project_id: The project ID

    Returns:
        True if quality gate passed, False otherwise
    """
    final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)
    detail = "passed" if final_gate_passed else "failed"
    emit_quality_gate_result(task_id, final_gate_passed, detail)
    return final_gate_passed
