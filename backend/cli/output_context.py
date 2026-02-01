"""Output context for CLI commands.

Passed via typer.Context.obj to avoid module-level mutable globals.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutputContext:
    """CLI output configuration passed through typer.Context.obj."""

    human: bool = False
    compact: bool = True
    progress_only: bool = False

    @property
    def is_compact(self) -> bool:
        """Check if compact TOON output is enabled."""
        return self.compact or self.progress_only

    @property
    def is_progress_only(self) -> bool:
        """Check if progress-only mode is enabled."""
        return self.progress_only

    @property
    def indent(self) -> int | None:
        """JSON indent level (2 for human-readable, None for compact)."""
        return 2 if self.human else None
