"""Refactor task generation from Explorer scan results."""

from __future__ import annotations

import logging
from typing import Any

from app.services.explorer import scan
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.projects import get_project_root_path
from app.storage.tasks import delete_task
from app.storage.tasks.queries import list_tasks
from app.tasks.autonomous.step_builders import build_refactor_steps, calculate_target_lines
from app.tasks.autonomous.task_builders import create_refactor_task

logger = logging.getLogger(__name__)

_SIZE_ISSUES = {"oversized", "large_file", "bloat_critical", "bloat_warning"}


def delete_existing_refactor_tasks(project_id: str) -> int:
    """Delete all existing refactor tasks for a project."""
    deleted = 0
    for task in list_tasks(project_id=project_id, task_type_filter="refactor", limit=500):
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            if delete_task(task_id):
                deleted += 1
                logger.info(f"Deleted refactor task {task_id}: {task.get('title', '')[:50]}")
        except Exception as e:
            logger.warning(f"Failed to delete task {task_id}: {e}")
    if deleted > 0:
        logger.info(f"Refactor task cleanup for {project_id}: deleted={deleted}")
    return deleted


def should_skip_refactor_target(
    project_id: str, relative_path: str, lines: int, target_lines: int, skip_existing: bool
) -> tuple[bool, str]:
    """Check if a refactor target should be skipped. Returns (should_skip, reason)."""
    if skip_existing and task_store.task_exists_for_file(project_id, relative_path):
        return True, f"Skipping {relative_path}: task already exists"
    if lines <= target_lines:
        return True, f"Skipping {relative_path}: {lines} lines already at/below target {target_lines}"
    if lines > 0 and (lines - target_lines) / lines < 0.20:
        pct = (lines - target_lines) / lines * 100
        return True, f"Skipping {relative_path}: reduction {pct:.0f}% below 20% threshold"
    return False, ""


def calculate_task_tier(complexity: float, lines: int) -> int:
    """Calculate task tier based on complexity and line count."""
    if complexity > 15 or lines > 500:
        return 3
    if complexity > 10 or lines > 300:
        return 2
    return 1


def _check_skip(
    project_id: str, relative_path: str, lines: int, target_lines: int,
    refactor_issues: list[str], skip_existing: bool,
) -> bool:
    """Return True if this target should be skipped."""
    if any(i in _SIZE_ISSUES for i in refactor_issues) or not refactor_issues:
        should_skip, reason = should_skip_refactor_target(
            project_id, relative_path, lines, target_lines, skip_existing
        )
        if should_skip:
            logger.info(reason)
            return True
    elif skip_existing and task_store.task_exists_for_file(project_id, relative_path):
        logger.info(f"Skipping {relative_path}: task already exists")
        return True
    return False


def process_refactor_target(
    project_id: str, target: dict[str, Any],
    project_root: str | None = None, skip_existing: bool = True,
) -> bool:
    """Process a single refactor target and create task if needed."""
    relative_path = target.get("path", "")
    lines = target.get("lines_of_code", 0)
    refactor_issues: list[str] = target.get("refactor_issues", [])
    target_lines = calculate_target_lines(lines)

    if _check_skip(project_id, relative_path, lines, target_lines, refactor_issues, skip_existing):
        return False

    complexity = target.get("complexity_score", 0)
    file_path = f"{project_root}/{relative_path}" if project_root else relative_path
    steps = build_refactor_steps(
        relative_path, file_path, lines, target_lines,
        relative_path.startswith("frontend/"), refactor_issues=refactor_issues,
    )
    task_id, issue_id = create_refactor_task(
        project_id=project_id, relative_path=relative_path, file_path=file_path,
        reason=target.get("reason", "High complexity"), complexity=complexity,
        lines=lines, target_lines=target_lines, priority=target.get("priority", "medium"),
        tier=calculate_task_tier(complexity, lines), steps=steps, refactor_issues=refactor_issues,
    )
    if task_id:
        logger.info(f"Created task {task_id} with spirit+criteria, linked to issue {issue_id}")
        return True
    return False


def generate_refactor_tasks_internal(
    project_id: str, skip_existing: bool, project_root: str | None = None
) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results."""
    targets = get_refactor_targets(project_id, limit=15).get("targets", [])
    created = sum(
        1 for t in targets if process_refactor_target(project_id, t, project_root, skip_existing)
    )
    return {"created_count": created, "scanned_count": len(targets), "skipped_count": len(targets) - created}


def regenerate_refactor_tasks_impl(project_id: str) -> dict[str, Any]:
    """Delete all existing refactor tasks and regenerate from current scan."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.error(f"Project {project_id} not found or has no root_path")
        return {"error": f"Project {project_id} not found", "deleted_count": 0, "created_count": 0, "scanned_count": 0}

    deleted_count = delete_existing_refactor_tasks(project_id)
    scan(project_id, "file")
    result = generate_refactor_tasks_internal(project_id, skip_existing=False, project_root=project_root)
    logger.info(
        f"Refactor task regeneration complete for {project_id}: "
        f"deleted={deleted_count}, created={result['created_count']}, "
        f"scanned={result['scanned_count']}, skipped={result['skipped_count']}"
    )
    return {"deleted_count": deleted_count, **result}
