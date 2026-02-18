"""Step verification logic - command execution and exit code checking."""

from __future__ import annotations

import subprocess

VERIFY_COMMAND_TIMEOUT = 300


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
        cwd: Working directory to run from. Required - raises ValueError if None.

        project_id: Project ID for resolving venv paths. When provided,
                    sets up the correct venv environment (handles worktrees).

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'passed': Exit code 0
        - 'failed': Exit code != 0
        - 'crashed': Exit code 126-127 or exception
    """
    from ..tasks.autonomous.verification_helpers import strip_venv_paths
    from .projects import build_project_env

    if not cwd:
        raise ValueError(
            "verify_command requires a working directory (cwd). "
            "Ensure project_id is set and worktree/project root is resolvable."
        )
    working_dir = cwd
    env = build_project_env(project_id, working_dir=cwd)
    verify_command = strip_venv_paths(verify_command)

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
