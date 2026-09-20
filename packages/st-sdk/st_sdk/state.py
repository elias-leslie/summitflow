"""Shared output-mode state for an ST extension process."""

from __future__ import annotations

_human_output = False
_compact_output = False
_progress_only = False


def set_human_output(enabled: bool) -> None:
    global _human_output
    _human_output = enabled


def set_compact_output(enabled: bool) -> None:
    global _compact_output
    _compact_output = enabled


def set_progress_only(enabled: bool) -> None:
    global _progress_only
    _progress_only = enabled


def is_human() -> bool:
    return _human_output


def is_compact() -> bool:
    return _compact_output


def is_progress_only() -> bool:
    return _progress_only

