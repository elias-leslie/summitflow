"""Refactor task generation from Explorer scan results."""

from __future__ import annotations

import logging
from typing import Any

from app.services.explorer import scan
from app.services.task_issue_mapper import link_issue_to_task
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.events import log_task_event
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.projects import get_project_root_path
from app.storage.task_spirit import get_task_spirit, update_task_spirit
from app.tasks.autonomous._issue_builder import create_refactor_issue
from app.tasks.autonomous.step_builders import build_refactor_steps, calculate_target_lines
from app.tasks.autonomous.task_builders import create_refactor_task
from app.tasks.explorer_resolution import check_and_close_resolved_issues

logger = logging.getLogger(__name__)

_SIZE_ISSUES = {"oversized", "large_file", "bloat_critical", "bloat_warning"}


def _ensure_refactor_scope(task_id: str, relative_path: str) -> None:
    """Backfill missing file scope on legacy/generated refactor tasks."""
    spirit = get_task_spirit(task_id) or {}
    context = spirit.get("context") if isinstance(spirit, dict) else {}
    if not isinstance(context, dict):
        context = {}
    existing_paths = context.get("files_to_modify")
    if isinstance(existing_paths, list) and relative_path in existing_paths:
        return

    merged_paths = [relative_path]
    if isinstance(existing_paths, list):
        merged_paths.extend(
            path
            for path in existing_paths
            if isinstance(path, str) and path and path != relative_path
        )
    update_task_spirit(task_id, context={**context, "files_to_modify": merged_paths})


def _backfill_existing_refactor_scopes(project_id: str, relative_path: str) -> None:
    """Repair legacy active refactor tasks that were created without scope."""
    for task_id in task_store.list_active_tasks_for_file(
        project_id,
        relative_path,
        task_type="refactor",
    ):
        _ensure_refactor_scope(task_id, relative_path)


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
            if skip_existing and "task already exists" in reason:
                _backfill_existing_refactor_scopes(project_id, relative_path)
            logger.info(reason)
            return True
    elif skip_existing and task_store.task_exists_for_file(project_id, relative_path):
        _backfill_existing_refactor_scopes(project_id, relative_path)
        logger.info(f"Skipping {relative_path}: task already exists")
        return True
    return False


def process_refactor_target(
    project_id: str, target: dict[str, Any],
    project_root: str | None = None, skip_existing: bool = True,
) -> tuple[bool, int]:
    """Process a single refactor target and create task if needed."""
    relative_path = target.get("path", "")
    lines = target.get("lines_of_code", 0)
    refactor_issues: list[str] = target.get("refactor_issues", [])
    target_lines = calculate_target_lines(lines)

    if _check_skip(project_id, relative_path, lines, target_lines, refactor_issues, skip_existing):
        return False, 0

    complexity = target.get("complexity_score", 0)
    file_path = f"{project_root}/{relative_path}" if project_root else relative_path
    issue_id = create_refactor_issue(
        project_id,
        relative_path,
        complexity,
        lines,
        target_lines,
        target.get("reason", "High complexity"),
    )
    canonical_task_id = _get_canonical_refactor_task_id(project_id, relative_path, issue_id)
    retired_count = 0
    if canonical_task_id:
        _ensure_refactor_scope(canonical_task_id, relative_path)
        retired_count = _retire_duplicate_refactor_tasks(project_id, relative_path, canonical_task_id)
        logger.info(
            "Skipping %s: canonical refactor task %s already exists",
            relative_path,
            canonical_task_id,
        )
        return False, retired_count

    steps = build_refactor_steps(
        relative_path, file_path, lines, target_lines,
        relative_path.startswith("frontend/"), refactor_issues=refactor_issues,
    )
    task_id, issue_id = create_refactor_task(
        project_id=project_id, relative_path=relative_path, file_path=file_path,
        reason=target.get("reason", "High complexity"), complexity=complexity,
        lines=lines, target_lines=target_lines, priority=target.get("priority", "medium"),
        tier=calculate_task_tier(complexity, lines), steps=steps, refactor_issues=refactor_issues,
        issue_id=issue_id,
    )
    if task_id:
        _ensure_refactor_scope(task_id, relative_path)
        retired_count += _retire_duplicate_refactor_tasks(project_id, relative_path, task_id)
        logger.info(f"Created task {task_id} with spirit+criteria, linked to issue {issue_id}")
        return True, retired_count
    return False, retired_count


def _get_canonical_refactor_task_id(project_id: str, relative_path: str, issue_id: int) -> str | None:
    """Return the canonical active refactor task for an issue/file, relinking when needed."""
    issue = qa_storage.get_issue(issue_id)
    linked_task_id = issue.get("st_task_id") if issue else None
    if isinstance(linked_task_id, str):
        linked_task = task_store.get_task(linked_task_id)
        if linked_task and linked_task.get("status") in {"pending", "running", "paused", "blocked", "ai_reviewing"}:
            return linked_task_id

    active_task_ids = task_store.list_active_tasks_for_file(project_id, relative_path, task_type="refactor")
    if not active_task_ids:
        return None
    # Select the lexicographically smallest task ID as canonical for determinism.
    # sorted(active_task_ids)[0] yields a stable tie-breaker across runs based on
    # ID string ordering (typically alphabetical). This is acceptable as a
    # deterministic fallback until a more explicit criterion (e.g., creation time)
    # is available.
    canonical_task_id = sorted(active_task_ids)[0]
    link_issue_to_task(issue_id, canonical_task_id)
    return canonical_task_id


def _retire_duplicate_refactor_tasks(project_id: str, relative_path: str, canonical_task_id: str) -> int:
    """Cancel extra active refactor tasks for the same file path."""
    retired_count = 0
    duplicate_task_ids = task_store.list_active_tasks_for_file(
        project_id,
        relative_path,
        task_type="refactor",
    )
    for duplicate_task_id in duplicate_task_ids:
        if duplicate_task_id == canonical_task_id:
            continue
        task_store.update_task(duplicate_task_id, status="cancelled")
        log_task_event(
            duplicate_task_id,
            f"Auto-cancelled duplicate refactor task for {relative_path}; canonical task is {canonical_task_id}",
            source="refactor_sync",
        )
        retired_count += 1
    return retired_count


def generate_refactor_tasks_internal(
    project_id: str, skip_existing: bool, project_root: str | None = None
) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results."""
    targets = get_refactor_targets(project_id, limit=15).get("targets", [])
    created = 0
    retired = 0
    for target in targets:
        was_created, retired_count = process_refactor_target(
            project_id,
            target,
            project_root,
            skip_existing,
        )
        created += 1 if was_created else 0
        retired += retired_count
    return {
        "created_count": created,
        "retired_count": retired,
        "scanned_count": len(targets),
        "skipped_count": len(targets) - created,
    }


def regenerate_refactor_tasks_impl(project_id: str) -> dict[str, Any]:
    """Scan, close resolved refactor tasks, and create only newly needed tasks."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.error(f"Project {project_id} not found or has no root_path")
        return {
            "error": f"Project {project_id} not found",
            "closed_count": 0,
            "created_count": 0,
            "scanned_count": 0,
        }

    scan(project_id, "file")
    closed_count = check_and_close_resolved_issues(project_id)
    result = generate_refactor_tasks_internal(project_id, skip_existing=True, project_root=project_root)
    logger.info(
        f"Refactor task sync complete for {project_id}: "
        f"closed={closed_count}, created={result['created_count']}, "
        f"retired={result['retired_count']}, "
        f"scanned={result['scanned_count']}, skipped={result['skipped_count']}"
    )
    return {"closed_count": closed_count, **result}
