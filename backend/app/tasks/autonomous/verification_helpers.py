"""Helper utilities for step verification.

Provides command expansion, output parsing, and file detection utilities.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import build_project_env

logger = get_logger(__name__)

COMMAND_ALIASES: dict[str, str] = {
    # dt commands run as-is - they have proper TOON output format
    # No expansion needed since dt is in PATH (~/.local/bin/dt)
}

# Regex patterns for .venv path stripping.
# Matches: .venv/bin/X, backend/.venv/bin/X
_VENV_BIN_PATTERN = re.compile(r"(?:backend/)?\.venv/bin/")
# Matches: source .venv/bin/activate &&, source backend/.venv/bin/activate &&
# Also: . .venv/bin/activate &&
_SOURCE_ACTIVATE_PATTERN = re.compile(
    r"(?:source|\.)\s+(?:backend/)?\.venv/bin/activate\s*&&\s*"
)


@dataclass
class VerificationResult:
    """Result of a step verification."""

    passed: bool
    step_number: int
    output: str
    returncode: int
    reason: str


def strip_venv_paths(cmd: str) -> str:
    """Strip .venv/bin/ prefixes from commands.

    Since build_project_env() puts the correct venv on PATH, relative
    .venv/bin/X paths are unnecessary and fail in worktrees where .venv
    doesn't exist. This rewrites them to bare binary names.

    Handles:
        .venv/bin/ruff check app/     -> ruff check app/
        backend/.venv/bin/pytest ...  -> pytest ...
        cd backend && .venv/bin/ty  -> cd backend && ty
        source .venv/bin/activate &&  -> (removed entirely)
    """
    if ".venv" not in cmd:
        return cmd

    # First remove "source .venv/bin/activate &&" patterns
    cmd = _SOURCE_ACTIVATE_PATTERN.sub("", cmd)

    # Then strip .venv/bin/ and backend/.venv/bin/ prefixes
    cmd = _VENV_BIN_PATTERN.sub("", cmd)

    return cmd


def expand_command(cmd: str) -> str:
    """Expand command aliases and strip .venv paths."""
    for alias, expansion in COMMAND_ALIASES.items():
        if cmd.strip().startswith(alias):
            remainder = cmd.strip()[len(alias) :].strip()
            cmd = f"{expansion} {remainder}".strip()
            break

    # Always strip .venv paths — venv is on PATH via build_project_env()
    return strip_venv_paths(cmd)


def detect_changed_files(project_path: str) -> list[str]:
    """Detect Python files changed in the last commit.

    Uses git diff HEAD~1 to find files modified by the agent.

    Returns:
        List of changed .py file paths relative to project root.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "--", "*.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("git_diff_failed", stderr=result.stderr[:200])
            return []

        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        logger.info("smoke_test_files_detected", count=len(files), files=files[:10])
        return files
    except Exception as e:
        logger.warning("smoke_test_detect_error", error=str(e))
        return []


def file_to_module(project_path: str, file_path: str) -> str | None:
    """Convert file path to Python module name.

    Args:
        project_path: Root path of the project
        file_path: Relative path like 'backend/cli/output.py'

    Returns:
        Module name like 'cli.output' or None if not importable.
    """
    if not file_path.endswith(".py"):
        return None
    file_path = file_path[:-12] if file_path.endswith("__init__.py") else file_path[:-3]

    # Handle backend/ prefix - strip it for module path
    if file_path.startswith("backend/"):
        file_path = file_path[8:]

    # Handle app/ prefix - keep it for summitflow backend structure
    # Convert path separators to dots
    module_name = file_path.replace("/", ".").replace("\\", ".")

    # Skip test files and migrations
    if "test" in module_name.lower() or "migration" in module_name.lower():
        return None

    return module_name if module_name else None


def resolve_working_directory(working_dir: str, command: str) -> str:
    """Resolve the effective working directory for a command.

    For pytest or python commands targeting backend, use backend/ as cwd.

    Args:
        working_dir: Base working directory
        command: Command to execute

    Returns:
        Effective working directory path
    """
    backend_dir = str(Path(working_dir) / "backend")
    if Path(backend_dir).is_dir() and (
        "pytest backend/" in command or "python -c" in command
    ):
        return backend_dir
    return working_dir


def adjust_command_for_cwd(command: str, original_cwd: str, new_cwd: str) -> str:
    """Adjust command paths when changing working directory.

    Args:
        command: Original command
        original_cwd: Original working directory
        new_cwd: New working directory

    Returns:
        Adjusted command with corrected paths
    """
    if new_cwd.endswith("/backend") and original_cwd != new_cwd:
        return command.replace("backend/tests/", "tests/")
    return command


def _execute_and_check(
    command: str,
    working_dir: str,
    timeout: int,
    env: dict[str, str],
) -> tuple[bool, str, str, int]:
    """Execute command and check exit code.

    Returns:
        Tuple of (passed, reason, output, returncode)
    """
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=working_dir,
        env=env,
    )

    output = result.stdout.strip()
    stderr = result.stderr.strip()
    full_output = f"{output}\n{stderr}".strip() if stderr else output

    passed = result.returncode == 0
    reason = "exit_code_0" if passed else f"exit_code_{result.returncode}"

    return passed, reason, full_output, result.returncode


def _missing_verify_command_result(step_num: int) -> VerificationResult:
    """Return a failed result for steps with no verify_command."""
    logger.warning(
        "Step has no verify_command — cannot pass without verification",
        step_num=step_num,
    )
    return VerificationResult(
        passed=False,
        step_number=step_num,
        output="Step has no verify_command. Every step must have verification.",
        returncode=-1,
        reason="missing_verify_command",
    )


def _prepare_verify_command(
    verify_cmd: str,
    working_dir: str,
    timeout: int,
    project_id: str | None,
) -> tuple[str, str, dict[str, Any], int]:
    """Expand command, resolve cwd, build env, and adjust timeout.

    Returns:
        Tuple of (expanded_cmd, effective_cwd, env, adjusted_timeout)
    """
    expanded_cmd = expand_command(verify_cmd)
    env = build_project_env(project_id, working_dir=working_dir)

    if any(cmd in expanded_cmd for cmd in ["dt ", "commit.sh", "npm run build"]):
        timeout = max(timeout, 300)

    effective_cwd = resolve_working_directory(working_dir, expanded_cmd)
    expanded_cmd = adjust_command_for_cwd(expanded_cmd, working_dir, effective_cwd)
    return expanded_cmd, effective_cwd, env, timeout


def _log_and_build_result(
    step_num: int,
    passed: bool,
    reason: str,
    full_output: str,
    returncode: int,
) -> VerificationResult:
    """Log verification outcome and return a VerificationResult."""
    logger.info(
        "Step verification result",
        step_num=step_num,
        passed=passed,
        returncode=returncode,
        reason=reason,
        output_preview=full_output[:200] if full_output else "(empty)",
    )
    debug_fn = debug_success if passed else debug_error
    debug_fn(
        f"Step {step_num} {'verified' if passed else 'failed'}",
        step=step_num,
        reason=reason if not passed else None,
        output_preview=full_output[:200] if full_output else "(empty)",
    )
    return VerificationResult(
        passed=passed,
        step_number=step_num,
        output=full_output[:1000],
        returncode=returncode,
        reason=reason,
    )
