"""Step verification logic - command execution and exit code checking."""

from __future__ import annotations

import subprocess

VERIFY_COMMAND_TIMEOUT = 300


def _classify_exit_code(exit_code: int) -> str:
    """Return 'passed' (0), 'failed' (1-125), or 'crashed' (126+)."""
    if exit_code == 0:
        return "passed"
    elif exit_code <= 125:
        return "failed"
    return "crashed"


def run_verify_command(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
    cwd: str | None = None,
    project_id: str | None = None,
) -> tuple[str, int, str]:
    """Execute a verify_command and return (status, exit_code, output).

    Status is 'passed' (exit 0), 'failed' (exit 1-125), or
    'crashed' (exit 126+ or exception). Raises ValueError if cwd is None.
    project_id is used to set up the correct venv environment.
    """
    from ..tasks.autonomous.verification_helpers import strip_venv_paths
    from .projects import build_project_env

    if not cwd:
        raise ValueError(
            "verify_command requires a working directory (cwd). "
            "Ensure project_id is set and worktree/project root is resolvable."
        )
    env = build_project_env(project_id, working_dir=cwd)
    verify_command = strip_venv_paths(verify_command)

    try:
        result = subprocess.run(
            ["bash", "-c", verify_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        exit_code = result.returncode
        output = result.stdout + result.stderr
        return (_classify_exit_code(exit_code), exit_code, output)

    except subprocess.TimeoutExpired:
        return ("crashed", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("crashed", -1, str(e))
