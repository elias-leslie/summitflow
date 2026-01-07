"""Implementation executor types and constants.

Shared data structures used across the implementation package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Default repository path
DEFAULT_REPO_PATH = Path("/home/kasadis/summitflow")

# Timeouts
AGENT_TIMEOUT_SECONDS = 300  # 5 minutes
SUBPROCESS_TIMEOUT_SECONDS = 120  # 2 minutes


@dataclass
class ExecutionResult:
    """Result of task execution."""

    success: bool
    iterations: int
    model_used: str
    models_tried: list[str] = field(default_factory=list)
    reason: str | None = None
    test_output: str | None = None
    error: str | None = None
