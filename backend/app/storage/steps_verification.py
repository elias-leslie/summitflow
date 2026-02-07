"""Step verification logic - command execution and output validation."""

from __future__ import annotations

import subprocess

VERIFY_COMMAND_TIMEOUT = 120


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
    project_id: str | None = None,
) -> tuple[str, int, str]:
    """Execute a verify_command and return classification.

    Args:
        verify_command: The bash command to run
        timeout: Command timeout in seconds
        cwd: Working directory to run from. If None, uses /home/kasadis/summitflow
             as fallback for backwards compatibility.
        project_id: Project ID for resolving venv paths. When provided,
                    sets up the correct venv environment (handles worktrees).

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'passed': Exit code 0
        - 'failed': Exit code != 0
        - 'crashed': Exit code 126-127 or exception
    """
    from .projects import build_project_env

    working_dir = cwd or "/home/kasadis/summitflow"
    env = build_project_env(project_id)

    try:
        result = subprocess.run(
            ["bash", "-c", verify_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
            env=env,
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
