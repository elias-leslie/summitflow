"""Implementation verification - Test running and criteria checking.

Runs external verification tools (pytest, pyright, ruff) and checks acceptance criteria.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage.connection import get_connection
from ...storage.criteria import get_effective_criteria
from .types import SUBPROCESS_TIMEOUT_SECONDS

logger = get_logger(__name__)


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

    # Run pytest
    try:
        pytest_result = subprocess.run(
            [".venv/bin/pytest", "-v", "--tb=short"],
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
            [".venv/bin/pyright", "app/"],
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
            [".venv/bin/ruff", "check", "app/"],
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


def check_acceptance_criteria(project_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Check if all acceptance criteria are verified.

    Uses get_effective_criteria to source from capability or task junction
    tables, with JSONB fallback for backward compatibility.

    Args:
        project_id: Project ID
        task: Task dict

    Returns:
        Dict with:
        - all_verified: bool
        - total: int
        - verified_count: int
        - unverified: list of criterion IDs
    """
    if not task:
        return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

    # Use get_effective_criteria for dual-source support
    with get_connection() as conn:
        criteria = get_effective_criteria(conn, project_id, task)

    if not criteria:
        return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

    verified_count = sum(1 for c in criteria if c.get("verified"))
    unverified = [c.get("criterion_id") for c in criteria if not c.get("verified")]

    return {
        "all_verified": len(unverified) == 0,
        "total": len(criteria),
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
