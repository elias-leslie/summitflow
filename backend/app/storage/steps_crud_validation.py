"""Validation utilities for step CRUD operations."""

from __future__ import annotations

import re

_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")

_TRIVIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^(true|:|exit\s+0)$"),
        "verify_command '{cmd}' always exits 0. Use a command that checks "
        "actual state: rg -q 'pattern' file, test -f path, pytest tests/test_foo.py -q",
    ),
    (
        re.compile(r"^#"),
        "verify_command is a comment, not executable. Use a shell command that exits non-zero on failure",
    ),
    (
        re.compile(r"^echo\s", re.IGNORECASE),
        "verify_command is echo-only (always exits 0). Append a real check: echo ... && rg -q 'pattern' file",
    ),
]


def sanitize_verify_command(cmd: str | None) -> str | None:
    """Reject verify_commands that are trivial or contain absolute paths.

    Raises ValueError for:
    - Trivial commands that always exit 0 (true, :, exit 0, echo-only, comments)
    - Absolute paths that break worktree isolation

    Silent nullification is avoided because verify_step treats
    None verify_command as passed.
    """
    if not cmd:
        return cmd

    stripped = cmd.strip()
    if not stripped:
        msg = "verify_command is empty. Every step needs: rg -q 'pattern' file, test -f path, or pytest"
        raise ValueError(msg)

    for pattern, msg_template in _TRIVIAL_PATTERNS:
        if pattern.match(stripped):
            # Echo-only: allow compound commands (echo ... && real_check)
            if "echo" in msg_template.lower() and "&&" in stripped:
                continue
            msg = msg_template.format(cmd=stripped)
            raise ValueError(msg)

    if _ABSOLUTE_CD_PATTERN.search(cmd) or _ABSOLUTE_PATH_PREFIX.search(cmd):
        msg = (
            "verify_command uses absolute path (breaks worktree isolation). "
            f"Use relative paths — commands run with cwd=worktree: {cmd[:120]}"
        )
        raise ValueError(msg)

    return cmd
