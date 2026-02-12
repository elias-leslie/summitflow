"""Extension request handling for retry loop."""

from __future__ import annotations

from typing import Any

from ....storage import agent_configs
from .agent_routing import EXTENSION_ATTEMPTS, detect_progress, request_extension
from .events import emit_log


def check_and_request_extension(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    project_path: str,
    project_id: str,
    extensions_granted: int,
) -> tuple[bool, int, str | None]:
    """Check progress and request extension if warranted.

    Returns:
        Tuple of (extension_approved, new_extensions_granted, guidance_text)
    """
    # Check if we've exceeded the max extensions limit
    max_extensions = agent_configs.get_max_extensions(project_id)
    if extensions_granted >= max_extensions:
        emit_log(
            task_id,
            "warn",
            f"Max extensions limit reached ({max_extensions}), cannot request more",
            source="supervisor",
            project_id=project_id,
        )
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
