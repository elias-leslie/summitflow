"""Typed output context passed to Typer owner callbacks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutputContext:
    human: bool = False
    compact: bool = True
    progress_only: bool = False

    @property
    def is_compact(self) -> bool:
        return self.compact or self.progress_only

    @property
    def is_progress_only(self) -> bool:
        return self.progress_only

    @property
    def indent(self) -> int | None:
        return 2 if self.human else None

