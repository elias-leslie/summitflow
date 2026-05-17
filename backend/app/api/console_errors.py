"""Console Error Capture API - Endpoints for frontend error reporting."""

import hashlib

from fastapi import APIRouter

from ..logging_config import get_logger
from ..storage.tasks.core import create_task
from ..storage.tasks.dedup import bug_task_exists_for_error
from .dependencies import validate_project_exists
from .quality_gate_models import ConsoleErrorRequest, ConsoleErrorResponse

logger = get_logger(__name__)

router = APIRouter()

_MAX_ERROR_PREVIEW = 80
_MAX_STACK_TRACE = 2000


def _compute_console_error_hash(error: str, stack: str | None) -> str:
    """Compute a stable hash for a console error.

    Args:
        error: Error message
        stack: Stack trace (optional)

    Returns:
        16-character hash
    """
    content = f"{error}|{stack or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _build_error_title(error: str) -> str:
    """Build a task title from the error message.

    Args:
        error: Full error message

    Returns:
        Formatted title with truncated error preview
    """
    error_preview = error[:_MAX_ERROR_PREVIEW]
    if len(error) > _MAX_ERROR_PREVIEW:
        error_preview += "..."
    return f"Fix: [Frontend] {error_preview}"


def _build_error_description(request: ConsoleErrorRequest, error_hash: str) -> str:
    """Build a task description with full error context.

    Args:
        request: Error request data from frontend
        error_hash: Computed hash of the error

    Returns:
        Formatted markdown description
    """
    description_parts = [
        f"**Captured:** {request.timestamp}",
        f"**URL:** {request.url}",
    ]
    if request.user_agent:
        description_parts.append(f"**User Agent:** {request.user_agent}")
    description_parts.extend(
        [
            "",
            "**Error:**",
            "```",
            request.error,
            "```",
        ]
    )
    if request.stack:
        description_parts.extend(
            [
                "",
                "**Stack Trace:**",
                "```",
                request.stack[:_MAX_STACK_TRACE],
                "```",
            ]
        )
    description_parts.extend(
        [
            "",
            f"**Error Hash:** {error_hash}",
            "",
            "This bug was auto-created from frontend console error capture.",
        ]
    )
    return "\n".join(description_parts)


def _create_error_task(
    project_id: str,
    request: ConsoleErrorRequest,
    title: str,
) -> ConsoleErrorResponse:
    """Create a bug task for a console error and return the response.

    Args:
        project_id: Project ID
        request: Error details from frontend
        title: Pre-built task title

    Returns:
        ConsoleErrorResponse with the created task ID
    """
    error_hash = _compute_console_error_hash(request.error, request.stack)
    description = _build_error_description(request, error_hash)

    task = create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=2,
        task_type="bug",
        complexity="STANDARD",
        execution_mode="autonomous",
    )

    logger.info(
        "created_console_error_task",
        task_id=task["id"],
        project_id=project_id,
        error_hash=error_hash,
    )

    return ConsoleErrorResponse(
        success=True,
        task_id=task["id"],
        message="Bug task created for console error",
    )


@router.post("/projects/{project_id}/errors/console")
async def capture_console_error(
    project_id: str,
    request: ConsoleErrorRequest,
) -> ConsoleErrorResponse:
    """Capture a frontend console error and create a bug task.

    This endpoint is called by frontend error handlers to report
    JavaScript errors for investigation.

    Deduplication: Won't create duplicate tasks for same error+stack
    within the last 24 hours.

    Args:
        project_id: Project ID
        request: Error details from frontend

    Returns:
        ConsoleErrorResponse with task info if created
    """
    validate_project_exists(project_id)

    title = _build_error_title(request.error)

    if bug_task_exists_for_error(project_id, title):
        logger.info(
            "skipping_duplicate_console_error",
            project_id=project_id,
            error=request.error[:50],
        )
        return ConsoleErrorResponse(
            success=True,
            message="Duplicate error - task already exists",
            is_duplicate=True,
        )

    return _create_error_task(project_id, request, title)
