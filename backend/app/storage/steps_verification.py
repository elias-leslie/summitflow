"""Step verification logic - command execution and output validation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Timeout for verify_command execution (120 seconds / 2 minutes)
# Increased from 30s to allow full test suites to complete
VERIFY_COMMAND_TIMEOUT = 120


def _resolve_venv_paths(cmd: str, cwd: str | None) -> str:
    """Resolve .venv paths to absolute paths.

    For multi-project tasks, if the command explicitly `cd`s to a different
    project's directory, we use that project's venv instead.

    Args:
        cmd: Command that may contain .venv references
        cwd: Working directory

    Returns:
        Command with absolute venv paths
    """
    if ".venv" not in cmd:
        return cmd

    if not cwd:
        return cmd

    from .projects import get_project_root_path

    # Check if command explicitly cd's to a different project's backend
    # Pattern: cd /home/kasadis/<project>/backend or cd /home/kasadis/<project>
    cd_match = re.search(r"cd\s+(/home/kasadis/([^/\s]+)(?:/backend)?)\s*&&", cmd)
    if cd_match:
        explicit_project = cd_match.group(2)
        explicit_repo = get_project_root_path(explicit_project)
        if explicit_repo:
            explicit_venv = Path(explicit_repo) / "backend" / ".venv"
            if explicit_venv.exists():
                abs_venv = f"{explicit_venv}/bin/"
                # Handle both `backend/.venv/bin/` and `.venv/bin/` patterns
                if "backend/.venv/bin/" in cmd:
                    return cmd.replace("backend/.venv/bin/", abs_venv)
                return cmd.replace(".venv/bin/", abs_venv)

    # Check if cwd has backend/.venv
    cwd_path = Path(cwd)
    if (cwd_path / "backend" / ".venv").exists():
        abs_venv = f"{cwd_path}/backend/.venv/bin/"
        # Handle both `backend/.venv/bin/` and `.venv/bin/` patterns
        if "backend/.venv/bin/" in cmd:
            return cmd.replace("backend/.venv/bin/", abs_venv)
        return cmd.replace(".venv/bin/", abs_venv)

    # Try parent directory (for when cwd is backend/)
    if cwd_path.name == "backend" and (cwd_path / ".venv").exists():
        abs_venv = f"{cwd_path}/.venv/bin/"
        if "backend/.venv/bin/" in cmd:
            # Strip redundant backend/ since we're already in backend/
            return cmd.replace("backend/.venv/bin/", abs_venv)
        return cmd.replace(".venv/bin/", abs_venv)

    return cmd


def _parse_expected(expected: str | None) -> tuple[str, str | None]:
    """Parse expected_output into (check_type, value).

    Returns:
        (check_type, value) where check_type is one of:
        - "exit_code": Check returncode == 0 (no output check)
        - "contains": Check value in output

    Exit code patterns (all mean "just check exit code = 0"):
        - "exit code 0", "exit code: 0"
        - "exit 0", "exit: 0", "exit:0"
        - "exit_code", "exitcode"
        - "success", "ok", "pass"
        - "lint:ok", "types:ok", "test:ok"
    """
    if not expected:
        return ("exit_code", None)

    expected_lower = expected.lower().strip()

    # Exit code patterns - just check returncode == 0
    exit_code_patterns = (
        "exit code",  # "exit code 0", "exit code: 0"
        "exit 0",
        "exit: 0",
        "exit:0",
        "exit_code",
        "exitcode",
        "success",
        "ok",
        "pass",
        "lint:ok",
        "types:ok",
        "test:ok",
    )
    if any(expected_lower.startswith(p) or expected_lower == p for p in exit_code_patterns):
        return ("exit_code", None)

    if expected_lower.startswith("contains:"):
        return ("contains", expected[9:].strip())

    return ("contains", expected)


def run_verify_command(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
    cwd: str | None = None,
) -> tuple[str, int, str]:
    """Execute a verify_command and return classification.

    Args:
        verify_command: The bash command to run
        timeout: Command timeout in seconds
        cwd: Working directory to run from. If None, uses /home/kasadis/summitflow
             as fallback for backwards compatibility.

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'passed': Exit code 0
        - 'failed': Exit code != 0
        - 'crashed': Exit code 126-127 or exception
    """
    # Default to summitflow for backwards compatibility
    working_dir = cwd or "/home/kasadis/summitflow"

    # Resolve .venv paths to absolute paths
    resolved_command = _resolve_venv_paths(verify_command, working_dir)

    try:
        # Use bash explicitly since commands may use bash-specific features like 'source'
        result = subprocess.run(
            ["bash", "-c", resolved_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        # Classify based on exit code
        if exit_code == 0:
            return ("passed", 0, output)
        elif 1 <= exit_code <= 125:
            return ("failed", exit_code, output)
        else:  # 126-127 = command not found or not executable
            return ("crashed", exit_code, output)

    except subprocess.TimeoutExpired:
        return ("crashed", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("crashed", -1, str(e))
