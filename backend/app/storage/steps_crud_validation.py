"""Validation utilities for step CRUD operations."""

from __future__ import annotations

import re

_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")


def sanitize_verify_command(cmd: str | None) -> str | None:
    """Reject verify_commands containing absolute paths that break worktree isolation.

    Raises ValueError instead of silently returning None, because silent nullification
    causes steps to auto-pass without actual verification (verify_step treats
    None verify_command as passed).
    """
    if not cmd:
        return cmd
    if _ABSOLUTE_CD_PATTERN.search(cmd) or _ABSOLUTE_PATH_PREFIX.search(cmd):
        msg = (
            f"verify_command contains absolute path (use relative paths — "
            f"commands run with cwd=worktree): {cmd[:120]}"
        )
        raise ValueError(msg)
    return cmd
