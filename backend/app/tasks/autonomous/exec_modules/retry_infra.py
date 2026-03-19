"""Infrastructure failure handling for retry loop."""

from __future__ import annotations

from typing import Any


def handle_infrastructure_failures(
    failed_steps: list[dict[str, Any]],
    subtask_id: str,
    task_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Return failed steps as-is.

    Auto-defect infrastructure handling has been removed along with the
    step layer.  All failures are now surfaced to the retry loop directly.
    """
    return failed_steps
