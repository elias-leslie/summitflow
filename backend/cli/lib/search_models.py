"""Shared models for the `st search` command."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SearchScope(StrEnum):
    """Search scope for st search."""

    AUTO = "auto"
    PROJECT = "project"
    CHECKOUT = "checkout"


@dataclass(frozen=True)
class SearchRoots:
    """Resolved search roots for the current CLI invocation."""

    scope: SearchScope
    effective_scope: str
    project_root: Path | None
    checkout_root: Path | None
    checkout_has_changes: bool = False
    # The checkout is a checkout of the project being searched (not e.g. a
    # -P <other-project> search run from an unrelated working directory).
    checkout_is_project: bool = False
