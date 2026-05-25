"""Refactor task generation from Explorer scan results."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.services.explorer import scan
from app.services.explorer.redundancy import cluster_signature
from app.services.refactor_promotion import assess_refactor_target
from app.services.task_issue_mapper import link_issue_to_task
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.connection import get_connection, get_cursor
from app.storage.events import log_task_event
from app.storage.explorer_analysis import (
    DEFAULT_REFACTOR_TARGET_LIMIT,
    get_promotable_refactor_paths,
    get_refactor_targets,
)
from app.storage.explorer_symbols import find_redundancy_candidates
from app.storage.projects import get_project_root_path
from app.storage.task_spirit import get_task_spirit, update_task_spirit
from app.tasks.autonomous._issue_builder import create_refactor_issue
from app.tasks.autonomous.step_builders import calculate_target_lines
from app.tasks.autonomous.task_builders import create_consolidation_task, create_refactor_task
from app.tasks.autonomous.upkeep_constants import (
    CONSOLIDATION_ALLOWLIST_ENV,
    DEFAULT_CONSOLIDATION_ALLOWLIST,
    SOURCE_CONSOLIDATE,
)
from app.tasks.autonomous.upkeep_prune import (
    close_obsolete_generated_task,
    prune_obsolete_upkeep_signal_tasks,
)
from app.tasks.explorer_resolution import check_and_close_resolved_issues

from ...logging_config import get_logger

logger = get_logger(__name__)

_SIZE_ISSUES = {"oversized", "large_file", "bloat_critical", "bloat_warning"}
_REFACTOR_PRUNE_STATUSES = ("pending", "paused", "failed")
# Per-scan cap on new consolidate-duplicate tasks: precision-first, never spam.
DEFAULT_CONSOLIDATION_CREATE_LIMIT = 5


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
    refactor_issues: list[str], skip_existing: bool, complexity: float,
    target: dict[str, Any],
) -> bool:
    """Return True if this target should be skipped."""
    assessment = assess_refactor_target(target)
    if not assessment.should_create_task:
        reason = "; ".join(assessment.suppression_reasons or ["insufficient evidence"])
        logger.info(
            "Skipping %s: %s",
            relative_path,
            reason,
        )
        return True
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
        logger.info("Skipping %s: task already exists", relative_path)
        return True
    return False


def _build_and_create_task(
    project_id: str, target: dict[str, Any],
    relative_path: str, lines: int, complexity: float,
    target_lines: int, refactor_issues: list[str], project_root: str | None,
) -> tuple[bool, int]:
    """Create a refactor issue + task, deduplicating against any existing canonical task."""
    file_path = f"{project_root}/{relative_path}" if project_root else relative_path
    if not Path(file_path).exists():
        logger.info("Skipping %s: file no longer exists on disk", relative_path)
        return False, 0
    issue_id = create_refactor_issue(
        project_id, relative_path, complexity, lines, target_lines,
        target.get("reason", "High complexity"),
    )
    canonical_task_id = _get_canonical_refactor_task_id(project_id, relative_path, issue_id)
    retired_count = 0
    if canonical_task_id:
        _ensure_refactor_scope(canonical_task_id, relative_path)
        retired_count = _retire_duplicate_refactor_tasks(project_id, relative_path, canonical_task_id)
        logger.info(
            "Skipping %s: canonical refactor task %s already exists",
            relative_path, canonical_task_id,
        )
        return False, retired_count

    task_id, issue_id = create_refactor_task(
        project_id=project_id, relative_path=relative_path, file_path=file_path,
        reason=target.get("reason", "High complexity"), complexity=complexity,
        lines=lines, target_lines=target_lines, priority=target.get("priority", "medium"),
        tier=calculate_task_tier(complexity, lines), steps=[], refactor_issues=refactor_issues,
        promotion_reasons=target.get("promotion_reasons"),
        promotion_confidence=target.get("confidence"),
        issue_id=issue_id,
    )
    if task_id:
        _ensure_refactor_scope(task_id, relative_path)
        retired_count += _retire_duplicate_refactor_tasks(project_id, relative_path, task_id)
        logger.info("Created task %s with spirit+criteria, linked to issue %s", task_id, issue_id)
        return True, retired_count
    return False, retired_count


def process_refactor_target(
    project_id: str, target: dict[str, Any],
    project_root: str | None = None, skip_existing: bool = True,
) -> tuple[bool, int]:
    """Process a single refactor target and create task if needed."""
    relative_path = target.get("path", "")
    lines = target.get("lines_of_code", 0)
    complexity = target.get("complexity_score", 0)
    refactor_issues: list[str] = target.get("refactor_issues", [])
    target_lines = calculate_target_lines(lines)

    if _check_skip(
        project_id, relative_path, lines, target_lines,
        refactor_issues, skip_existing, complexity, target,
    ):
        return False, 0

    return _build_and_create_task(
        project_id, target, relative_path, lines, complexity,
        target_lines, refactor_issues, project_root,
    )


def _get_canonical_refactor_task_id(project_id: str, relative_path: str, issue_id: int) -> str | None:
    """Return the canonical active refactor task for an issue/file, relinking when needed."""
    issue = qa_storage.get_issue(issue_id)
    linked_task_id = issue.get("st_task_id") if issue else None
    if isinstance(linked_task_id, str):
        linked_task = task_store.get_task(linked_task_id)
        if linked_task and linked_task.get("status") in {"pending", "running"}:
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


def _candidate_generated_refactor_tasks(project_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id,
                t.status,
                t.started_at,
                t.updated_at,
                t.total_sessions,
                t.commits,
                t.title,
                ts.context,
                q.file_path,
                q.status
            FROM tasks t
            LEFT JOIN task_spirit ts ON ts.task_id = t.id
            LEFT JOIN qa_issues q ON q.st_task_id = t.id
                AND q.project_id = t.project_id
                AND q.issue_type = 'complexity'
            WHERE t.project_id = %s
              AND t.task_type = 'refactor'
              AND t.status = ANY(%s)
              AND (q.id IS NOT NULL OR 'auto-generated' = ANY(t.labels))
              AND (ts.context -> 'upkeep' ->> 'signal_type') IS DISTINCT FROM 'consolidate-duplicate'
            """,
            (project_id, list(_REFACTOR_PRUNE_STATUSES)),
        )
        rows = cur.fetchall()
    tasks: list[dict[str, Any]] = []
    for row in rows:
        context = row[7] if isinstance(row[7], dict) else {}
        files = context.get("files_to_modify")
        relative_path = files[0] if isinstance(files, list) and files else row[8]
        tasks.append(
            {
                "id": row[0],
                "status": row[1],
                "started_at": row[2],
                "updated_at": row[3],
                "total_sessions": row[4],
                "commits": row[5],
                "title": row[6],
                "relative_path": relative_path,
                "issue_status": row[9],
            }
        )
    return tasks


def _prune_obsolete_refactor_tasks(
    project_id: str,
    active_paths: set[str],
    project_root: str | None,
) -> dict[str, int]:
    counts = {"deleted": 0, "completed": 0, "cancelled": 0, "skipped": 0, "skipped_active": 0}
    for task in _candidate_generated_refactor_tasks(project_id):
        relative_path = task.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            counts["skipped"] += 1
            continue
        file_path = Path(project_root, relative_path) if project_root else Path(relative_path)
        still_needed = relative_path in active_paths and file_path.exists()
        if still_needed:
            counts["skipped"] += 1
            continue
        reason = (
            f"Generated refactor source no longer active for {relative_path}"
            if file_path.exists()
            else f"Generated refactor target no longer exists: {relative_path}"
        )
        result = close_obsolete_generated_task(
            task,
            reason=reason,
            resolved=file_path.exists() or task.get("issue_status") == "resolved",
            deletion_source="routine-upkeep:prune-refactors",
        )
        counts[result] = counts.get(result, 0) + 1
    return counts


def generate_refactor_tasks_internal(
    project_id: str,
    skip_existing: bool,
    project_root: str | None = None,
    create_limit: int | None = None,
) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results."""
    targets = get_refactor_targets(
        project_id,
        limit=DEFAULT_REFACTOR_TARGET_LIMIT,
    ).get("targets", [])
    active_paths = get_promotable_refactor_paths(project_id)
    pruned = _prune_obsolete_refactor_tasks(project_id, active_paths, project_root)
    created = 0
    retired = 0
    for target in targets:
        if create_limit is not None and created >= create_limit:
            continue
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
        "pruned_count": pruned["deleted"] + pruned["completed"] + pruned["cancelled"],
        "prune": pruned,
        "scanned_count": len(targets),
        "skipped_count": len(targets) - created,
    }


def _open_consolidation_source_keys(project_id: str) -> set[str]:
    """Source keys of consolidation tasks that still hold an open (non-terminal) slot."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ts.context -> 'upkeep' ->> 'source_key'
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status NOT IN ('completed', 'cancelled')
              AND (ts.context -> 'upkeep' ->> 'signal_type') = %s
            """,
            (project_id, SOURCE_CONSOLIDATE),
        )
        return {str(row[0]) for row in cur.fetchall() if row[0]}


def _member_files_present(project_root: str | None, paths: set[str]) -> int:
    """Count how many of a cluster's member files still exist on disk."""
    present = 0
    for relative_path in paths:
        file_path = Path(project_root, relative_path) if project_root else Path(relative_path)
        if file_path.exists():
            present += 1
    return present


def _consolidation_enabled(project_id: str) -> bool:
    """Whether consolidate-duplicate filing is rolled out to this project.

    Reads ``CONSOLIDATION_PROJECT_ALLOWLIST``: unset → conservative default
    allowlist; ``"*"`` → every project; otherwise a comma-separated list.
    """
    raw = os.getenv(CONSOLIDATION_ALLOWLIST_ENV)
    if raw is None:
        allowed: frozenset[str] = DEFAULT_CONSOLIDATION_ALLOWLIST
    elif raw.strip() == "*":
        return True
    else:
        allowed = frozenset(p.strip() for p in raw.split(",") if p.strip())
    return project_id in allowed


def generate_consolidation_tasks_internal(
    project_id: str,
    project_root: str | None = None,
    create_limit: int | None = DEFAULT_CONSOLIDATION_CREATE_LIMIT,
) -> dict[str, int]:
    """Create/retire consolidate-duplicate tasks from the redundancy detector.

    The detector's proven precision + the 2-3-member cap (in
    ``find_redundancy_candidates``) are the gate; the routine-upkeep
    source_key/signal_type contract gives dedupe and stale-task retirement for
    free via ``prune_obsolete_upkeep_signal_tasks``.

    Gated by a per-project rollout allowlist (see ``_consolidation_enabled``)
    so the pipeline does not auto-file on projects where the detector's
    precision has not yet been reviewed.
    """
    if not _consolidation_enabled(project_id):
        logger.info(
            "consolidate-duplicate filing skipped for %s (not in rollout allowlist)",
            project_id,
        )
        return {
            "consolidation_created": 0,
            "consolidation_candidates": 0,
            "consolidation_pruned": 0,
        }

    fresh: dict[str, list[dict[str, Any]]] = {}
    for cluster in find_redundancy_candidates(project_id):
        paths = {str(m.get("file_path")) for m in cluster.members if m.get("file_path")}
        if _member_files_present(project_root, paths) < 2:
            continue  # duplication already resolved on disk — not a live cluster
        source_key = f"upkeep:{SOURCE_CONSOLIDATE}:{cluster_signature(cluster)}"
        fresh[source_key] = cluster.members

    pruned = prune_obsolete_upkeep_signal_tasks(
        project_id, SOURCE_CONSOLIDATE, active_source_keys=set(fresh),
    )

    open_keys = _open_consolidation_source_keys(project_id)
    created = 0
    for source_key, members in fresh.items():
        if create_limit is not None and created >= create_limit:
            break
        if source_key in open_keys:
            continue  # already has an open consolidation task
        if create_consolidation_task(project_id, members, source_key):
            created += 1

    return {
        "consolidation_created": created,
        "consolidation_candidates": len(fresh),
        "consolidation_pruned": (
            pruned["deleted"] + pruned["completed"] + pruned["cancelled"]
        ),
    }


def regenerate_refactor_tasks_impl(
    project_id: str,
    create_limit: int | None = None,
    *,
    refresh_scan: bool = True,
) -> dict[str, Any]:
    """Scan, close resolved refactor tasks, and create only newly needed tasks."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.error("Project %s not found or has no root_path", project_id)
        return {
            "error": f"Project {project_id} not found",
            "closed_count": 0,
            "created_count": 0,
            "scanned_count": 0,
        }

    if refresh_scan:
        scan(project_id, "file")
    closed_count = check_and_close_resolved_issues(project_id)
    result = generate_refactor_tasks_internal(
        project_id,
        skip_existing=True,
        project_root=project_root,
        create_limit=create_limit,
    )
    consolidation = generate_consolidation_tasks_internal(project_id, project_root)
    logger.info(
        "Refactor task sync complete for %s: closed=%d, created=%d, retired=%d, scanned=%d, "
        "skipped=%d, consolidation_created=%d, consolidation_pruned=%d",
        project_id, closed_count, result['created_count'],
        result['retired_count'], result['scanned_count'], result['skipped_count'],
        consolidation['consolidation_created'], consolidation['consolidation_pruned'],
    )
    return {"closed_count": closed_count, **result, **consolidation}
