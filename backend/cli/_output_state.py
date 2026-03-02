"""Output mode state management for CLI."""

from __future__ import annotations

# Module-level flags for output modes
_human_output: bool = False
_compact_output: bool = False
_progress_only: bool = False


def set_human_output(enabled: bool) -> None:
    """Enable or disable human-readable (pretty-printed) output."""
    global _human_output
    _human_output = enabled


def set_compact_output(enabled: bool) -> None:
    """Enable or disable compact TOON-style output."""
    global _compact_output
    _compact_output = enabled


def set_progress_only(enabled: bool) -> None:
    """Enable progress-only mode (single line summary)."""
    global _progress_only
    _progress_only = enabled


def is_compact() -> bool:
    """Check if compact output mode is enabled."""
    return _compact_output


def is_progress_only() -> bool:
    """Check if progress-only mode is enabled."""
    return _progress_only
