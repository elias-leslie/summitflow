"""Validation utilities for step CRUD operations."""

from __future__ import annotations

import json
import re
from pathlib import Path

_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")

_TRIVIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^(true|:|exit\s+0)$"),
        "verify_command '{cmd}' always exits 0. Use a command that checks "
        "actual state: rg -q 'pattern' file, test -f path, dt pytest tests/test_foo.py -q",
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


def _load_registry_patterns() -> list[tuple[str, list[re.Pattern[str]]]]:
    """Load redirect patterns from tool-registry.json (cached at module level)."""
    try:
        registry_path = (
            Path(__file__).resolve().parents[3] / "scripts" / "lib" / "tool-registry.json"
        )
        with open(registry_path) as f:
            data = json.load(f)
        result: list[tuple[str, list[re.Pattern[str]]]] = []
        for tool in data.get("tools", []):
            raw_patterns = tool.get("redirect_patterns", [])
            if raw_patterns:
                compiled = [re.compile(p) for p in raw_patterns]
                result.append((tool["name"], compiled))
        return result
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


_REGISTRY_PATTERNS = _load_registry_patterns()


def _is_raw_tool_match(cmd: str, pattern: re.Pattern[str]) -> bool:
    """Return True if cmd contains a raw (unwrapped) tool match for pattern."""
    for match in pattern.finditer(cmd):
        before = cmd[: match.start()]
        if not re.search(r"\bdt\s+$", before):
            return True
    return False


def check_raw_tool_usage(cmd: str) -> str | None:
    """Check if command uses raw tools that should be wrapped by dt.

    Returns error message if a raw tool is detected, None otherwise.
    Loaded from tool-registry.json redirect_patterns.
    """
    for tool_name, patterns in _REGISTRY_PATTERNS:
        for pattern in patterns:
            if _is_raw_tool_match(cmd, pattern):
                return (
                    f"Raw '{tool_name}' in verify_command — "
                    f"use 'dt {tool_name}' instead: {cmd[:120]}"
                )
    return None


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

    raw_tool_error = check_raw_tool_usage(stripped)
    if raw_tool_error:
        raise ValueError(raw_tool_error)

    return cmd
