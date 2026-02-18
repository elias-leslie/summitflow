"""Tool runners for AI review task (pytest, pre-commit, types)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)


def run_command(
    cmd: list[str],
    cwd: Path,
    timeout: int = 300,
) -> tuple[bool, str]:
    """Run a command and return (success, output).

    Args:
        cmd: Command to run
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def run_pytest(project_path: Path) -> dict[str, Any]:
    """Run pytest with coverage threshold.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    backend_path = project_path / "backend"
    if not backend_path.exists():
        return {"status": "skip", "reason": "No backend directory"}

    venv_pytest = backend_path / ".venv" / "bin" / "pytest"
    if not venv_pytest.exists():
        return {"status": "skip", "reason": "No pytest in venv"}

    success, output = run_command(
        [str(venv_pytest), "--tb=short", "-q"],
        cwd=backend_path,
        timeout=300,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def run_precommit(project_path: Path) -> dict[str, Any]:
    """Run pre-commit hooks.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    success, output = run_command(
        ["pre-commit", "run", "--all-files"],
        cwd=project_path,
        timeout=180,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def run_types(project_path: Path) -> dict[str, Any]:
    """Run ty type checking.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    backend_path = project_path / "backend"
    if not backend_path.exists():
        return {"status": "skip", "reason": "No backend directory"}

    if not shutil.which("ty"):
        return {"status": "skip", "reason": "ty not found"}

    venv_python = backend_path / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return {"status": "skip", "reason": "No venv python in backend/"}

    success, output = run_command(
        ["ty", "check", "--python", str(venv_python), "app/"],
        cwd=backend_path,
        timeout=120,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }
