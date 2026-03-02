"""Extension request handling for retry loop."""

from __future__ import annotations

from ....storage import agent_configs
from .agent_routing import EXTENSION_ATTEMPTS, detect_progress, request_extension
from .events import emit_log


def _check_max_extensions_reached(
    task_id: str,
    project_id: str,
    extensions_granted: int,
) -> bool:
    """Return True if the max extensions limit has been reached, emitting a warning."""
    max_extensions = agent_configs.get_max_extensions(project_id)
    if extensions_granted < max_extensions:
        return False
    emit_log(
        task_id,
        "warn",
        f"Max extensions limit reached ({max_extensions}), cannot request more",
        source="supervisor",
        project_id=project_id,
    )
    return True


def _grant_extension(
    task_id: str,
    project_id: str,
    extensions_granted: int,
    ext_guidance: str | None,
) -> tuple[bool, int, str | None]:
    """Log a granted extension and return the updated state."""
    new_extensions = extensions_granted + 1
    emit_log(
        task_id,
        "info",
        f"Supervisor granted extension #{new_extensions} "
        f"({EXTENSION_ATTEMPTS} more attempts)",
        source="supervisor",
        project_id=project_id,
    )
    return True, new_extensions, ext_guidance


def check_and_request_extension(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    steps: list[dict[str, object]],
    step_results: list[dict[str, object]],
    project_path: str,
    project_id: str,
    extensions_granted: int,
) -> tuple[bool, int, str | None]:
    """Check progress and request extension if warranted.

    Returns:
        Tuple of (extension_approved, new_extensions_granted, guidance_text)
    """
    if _check_max_extensions_reached(task_id, project_id, extensions_granted):
        return False, extensions_granted, None

    progress = detect_progress(subtask_id, steps, step_results, project_path)
    if not progress:
        return False, extensions_granted, None

    approved, ext_guidance = request_extension(
        task_id,
        subtask_short_id,
        step_results,
        progress,
        project_id=project_id,
        prior_extensions=extensions_granted,
    )

    if not approved:
        return False, extensions_granted, None

    return _grant_extension(task_id, project_id, extensions_granted, ext_guidance)
