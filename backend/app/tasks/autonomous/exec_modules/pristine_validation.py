"""Pre-execution quality gate policy."""

from __future__ import annotations

from .events import emit_log


def validate_pristine_codebase(task_id: str, project_id: str) -> bool:
    """Do not block automated execution on an unrelated project baseline."""
    emit_log(
        task_id,
        "info",
        "Skipping baseline quality pre-check; execution will verify task-scoped changes.",
        project_id=project_id,
    )
    return True
