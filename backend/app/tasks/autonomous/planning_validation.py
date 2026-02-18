"""Validation logic for autonomous planning verify commands.

Ensures verify commands are safe, effective, and worktree-compatible.
"""

from __future__ import annotations

import re
from typing import Any

from ...logging_config import get_logger
from ...storage.steps_crud_validation import check_raw_tool_usage

logger = get_logger(__name__)

# Patterns for absolute paths (break worktree isolation)
_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")

# Patterns for suboptimal commands (warnings)
_SMALL_CONTEXT_WINDOW = re.compile(r"-A[1-5]\b")
_CHAINED_RG_PIPE = re.compile(r"rg\s.+\|\s*rg")
_HEAD_TAIL_USAGE = re.compile(r"\bhead\b|\btail\b")

# Patterns for trivial commands (always exit 0)
_TRIVIAL_NOOP = re.compile(r"^(true|:|exit\s+0)$")
_ECHO_ONLY = re.compile(r"^echo\s", re.IGNORECASE)
_COMMENT_ONLY = re.compile(r"^#")


def _is_trivial_command(cmd: str) -> str | None:
    """Return error message if verify_command is trivial (always exits 0), else None."""
    stripped = cmd.strip()
    if not stripped:
        return "verify_command is empty. Every step needs: rg -q 'pattern' file, test -f path, or pytest"
    if _TRIVIAL_NOOP.match(stripped):
        return (
            f"verify_command '{stripped}' always exits 0. Use a command that checks "
            "actual state: rg -q 'pattern' file, test -f path, pytest tests/test_foo.py -q"
        )
    if _COMMENT_ONLY.match(stripped):
        return "verify_command is a comment, not executable. Use a shell command that exits non-zero on failure"
    if _ECHO_ONLY.match(stripped) and "&&" not in stripped:
        return "verify_command is echo-only (always exits 0). Append a real check: echo ... && rg -q 'pattern' file"
    return None


def _validate_verify_command(cmd: str) -> str | None:
    """Return error message if verify_command has absolute paths, else None."""
    if _ABSOLUTE_CD_PATTERN.search(cmd):
        return (
            "verify_command uses absolute path (breaks worktree isolation). "
            "Use relative paths — commands run with cwd=worktree"
        )
    if _ABSOLUTE_PATH_PREFIX.search(cmd):
        return (
            "verify_command uses absolute path (breaks worktree isolation). "
            "Use relative paths — commands run with cwd=worktree"
        )
    return None


def validate_and_fix_plan(plan: dict[str, Any]) -> None:
    """Validate and fix common issues in verify_commands.

    Args:
        plan: Plan data with subtasks containing steps with verify_commands

    Raises:
        ValueError: If validation fails on trivial commands
    """
    for subtask in plan.get("subtasks", []):
        for step in subtask.get("steps", []):
            verify = step.get("verify_command", "")

            if verify:
                # Block trivial commands (always exit 0)
                trivial_error = _is_trivial_command(verify)
                if trivial_error:
                    raise ValueError(
                        f"Step in subtask {subtask.get('subtask_id')}: {trivial_error}"
                    )

                # Auto-fix absolute cd paths: strip "cd /abs/path && " prefix
                # since commands already run with cwd=worktree
                cd_match = _ABSOLUTE_CD_PATTERN.search(verify)
                if cd_match:
                    # Strip everything up to and including the "&&" after the cd
                    fixed = re.sub(r"cd\s+/[^\s;|&]+\s*&&\s*", "", verify).strip()
                    if fixed:
                        logger.info(
                            "auto_fixed_absolute_cd",
                            subtask=subtask.get("subtask_id"),
                            original=verify[:80],
                            fixed=fixed[:80],
                        )
                        step["verify_command"] = fixed
                        verify = fixed
                    else:
                        raise ValueError(
                            f"Step in subtask {subtask.get('subtask_id')}: "
                            "verify_command is only a cd to absolute path"
                        )

                # Block remaining absolute paths that can't be auto-fixed
                if _ABSOLUTE_PATH_PREFIX.search(verify):
                    raise ValueError(
                        f"Step in subtask {subtask.get('subtask_id')}: "
                        "verify_command uses absolute path (breaks worktree isolation). "
                        "Use relative paths — commands run with cwd=worktree"
                    )

                # Fix cat | grep -> rg
                if "cat " in verify and "| grep" in verify:
                    step["verify_command"] = re.sub(
                        r"cat\s+(\S+)\s*\|\s*grep\s+(.+)",
                        r"rg \2 \1",
                        verify,
                    )

                # Fix grep -> rg
                elif verify.startswith("grep "):
                    step["verify_command"] = "rg " + verify[5:]

                # Warn about suboptimal patterns
                if _SMALL_CONTEXT_WINDOW.search(verify):
                    logger.warning(
                        "small_context_window",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )

                if _CHAINED_RG_PIPE.search(verify):
                    logger.warning(
                        "chained_rg_pipe",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )

                if _HEAD_TAIL_USAGE.search(verify):
                    logger.warning(
                        "head_tail_usage",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )

                # Block raw tool usage (must use dt wrapper)
                raw_tool_error = check_raw_tool_usage(verify)
                if raw_tool_error:
                    raise ValueError(
                        f"Step in subtask {subtask.get('subtask_id')}: {raw_tool_error}"
                    )
