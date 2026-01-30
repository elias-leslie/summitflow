"""Implementation verification - Test running and step completion checking.

Runs external verification tools (pytest, pyright, ruff) and checks step completion.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage.steps import get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task
from .types import SUBPROCESS_TIMEOUT_SECONDS

logger = get_logger(__name__)


def _resolve_venv_path(cmd_path: str, repo_path: Path) -> str:
    """Resolve .venv paths to use main repo's venv for worktrees.

    Worktrees don't include virtualenvs, so we need to point to the main repo.

    Args:
        cmd_path: Command path like ".venv/bin/pytest"
        repo_path: Repository path (may be worktree or main repo)

    Returns:
        Resolved path string
    """
    if not cmd_path.startswith(".venv/"):
        return cmd_path

    # Check if running in a worktree: /tmp/summitflow-worktrees/<project>/task-xxx
    repo_str = str(repo_path)
    worktree_match = re.match(r"/tmp/summitflow-worktrees/([^/]+)/", repo_str)
    if worktree_match:
        project_id = worktree_match.group(1)
        from ...storage.projects import get_project_root_path

        main_repo = get_project_root_path(project_id)
        if main_repo:
            main_venv = Path(main_repo) / "backend" / ".venv"
            if main_venv.exists():
                return str(main_venv / cmd_path[6:])  # Skip ".venv/"

    # Not a worktree - try parent repo's venv
    backend_venv = repo_path / "backend" / ".venv"
    if backend_venv.exists():
        return str(backend_venv / cmd_path[6:])

    # Fallback to relative path
    return cmd_path


def run_verification(
    repo_path: Path,
    files: list[str],
    capability_id: int | str,
) -> dict[str, Any]:
    """Run external verification (pytest, pyright, ruff).

    Args:
        repo_path: Path to repository (main or worktree)
        files: List of affected files
        capability_id: Capability ID or "general" for standalone tasks

    Returns:
        Dict with success, output, pytest_output, static_output
    """
    result: dict[str, Any] = {
        "success": False,
        "output": "",
        "pytest_output": "",
        "static_output": "",
    }

    backend_path = repo_path / "backend"

    # Resolve venv paths for worktrees
    pytest_path = _resolve_venv_path(".venv/bin/pytest", repo_path)
    pyright_path = _resolve_venv_path(".venv/bin/pyright", repo_path)
    ruff_path = _resolve_venv_path(".venv/bin/ruff", repo_path)

    # Run pytest
    try:
        pytest_result = subprocess.run(
            [pytest_path, "-v", "--tb=short"],
            cwd=backend_path,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        result["pytest_output"] = pytest_result.stdout + pytest_result.stderr
        pytest_passed = pytest_result.returncode == 0
    except subprocess.TimeoutExpired:
        result["pytest_output"] = "pytest timed out"
        pytest_passed = False
    except Exception as e:
        result["pytest_output"] = f"pytest error: {e}"
        pytest_passed = False

    # Run pyright
    try:
        pyright_result = subprocess.run(
            [pyright_path, "app/"],
            cwd=backend_path,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        pyright_passed = pyright_result.returncode == 0
        result["static_output"] += f"pyright:\n{pyright_result.stdout}\n"
    except subprocess.TimeoutExpired:
        result["static_output"] += "pyright timed out\n"
        pyright_passed = False
    except Exception as e:
        result["static_output"] += f"pyright error: {e}\n"
        pyright_passed = False

    # Run ruff
    try:
        ruff_result = subprocess.run(
            [ruff_path, "check", "app/"],
            cwd=backend_path,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        ruff_passed = ruff_result.returncode == 0
        result["static_output"] += f"ruff:\n{ruff_result.stdout}\n"
    except subprocess.TimeoutExpired:
        result["static_output"] += "ruff timed out\n"
        ruff_passed = False
    except Exception as e:
        result["static_output"] += f"ruff error: {e}\n"
        ruff_passed = False

    result["success"] = pytest_passed and pyright_passed and ruff_passed
    result["output"] = result["pytest_output"] + result["static_output"]

    return result


def check_step_completion(project_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Check if all steps are verified (step-level verification).

    Checks that all steps across all subtasks are marked as passed.

    Args:
        project_id: Project ID (unused but kept for API compatibility)
        task: Task dict with 'id' field

    Returns:
        Dict with:
        - all_verified: bool
        - total: int (total steps)
        - verified_count: int (passed steps)
        - unverified: list of step IDs that haven't passed
    """
    if not task:
        return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

    task_id = task.get("id")
    if not task_id:
        return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

    # Get all subtasks for the task
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

    total = 0
    verified_count = 0
    unverified: list[str] = []

    for subtask in subtasks:
        subtask_id = subtask.get("id", "")
        steps = get_steps_for_subtask(subtask_id)
        for step in steps:
            total += 1
            step_id = f"{subtask_id}.{step.get('step_number', 0)}"
            if step.get("passes"):
                verified_count += 1
            else:
                unverified.append(step_id)

    return {
        "all_verified": len(unverified) == 0,
        "total": total,
        "verified_count": verified_count,
        "unverified": unverified,
    }


def compute_error_signature(error_output: str) -> str:
    """Compute a signature for error output to detect repeated failures."""
    lines = []
    for line in error_output.split("\n"):
        if "FAILED" in line or "error:" in line.lower() or "Error" in line:
            lines.append(line.strip())

    signature_text = "\n".join(sorted(lines))
    return hashlib.md5(signature_text.encode()).hexdigest()
