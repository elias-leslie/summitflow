"""Quality gate checking functions."""

from __future__ import annotations

import subprocess

from .events import emit_log
from .quality_utils import find_dev_tools


def run_final_quality_gate(
    task_id: str, project_path: str, project_id: str
) -> bool:
    """Run dt --quick as final quality gate before AI review.

    Args:
        task_id: Task ID for logging
        project_path: Path to the project/worktree
        project_id: Project ID for logging

    Returns:
        True if quality gate passes, False otherwise
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return True

    emit_log(
        task_id,
        "info",
        "Running final quality gate (dt --quick)...",
        source="quality",
        project_id=project_id,
    )

    try:
        result = subprocess.run(
            [dt_cmd, "--quick"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        passed = result.returncode == 0
        if passed:
            emit_log(
                task_id,
                "info",
                "Final quality gate passed",
                source="quality",
                project_id=project_id,
            )
        else:
            output = (result.stdout + result.stderr)[:500]
            emit_log(
                task_id,
                "warn",
                f"Final quality gate failed: {output}",
                source="quality",
                project_id=project_id,
            )
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


def auto_fix_quality(project_path: str) -> bool:
    """Run dt --fix to attempt auto-fixing quality issues.

    Returns:
        True if dt --fix ran successfully
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return False

    try:
        result = subprocess.run(
            [dt_cmd, "--fix"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except Exception:
        return False
