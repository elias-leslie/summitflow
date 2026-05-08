"""Baseline quality gate blockers for task execution."""

from __future__ import annotations

import hashlib
from typing import Any

from app.storage import log_task_event, task_dependencies
from app.storage import tasks as task_store
from app.storage.connection import get_cursor
from app.storage.task_spirit import get_task_spirit
from app.tasks.autonomous.upkeep_constants import SOURCE_QUALITY, TASK_TYPE_BUG
from app.tasks.autonomous.upkeep_models import SignalTaskSpec
from app.tasks.autonomous.upkeep_signals import (
    create_signal_task,
    source_key,
    task_exists_for_upkeep_source,
)

BASELINE_QUALITY_MARKER = "baseline_quality_gate"
QUALITY_BLOCKER_REASON = "quality_gate_blocked"
QUALITY_FIX_AGENT = "debugger"


def _quality_lines(output: str) -> list[str]:
    lines: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if (
            upper.startswith(("ARCH:", "LINT:", "TYPES:", "TEST:", "BIOME:", "TSC:"))
            or "FAILED" in upper
            or "ERROR" in upper
        ):
            lines.append(line[:300])
    return lines[:80]


def quality_gate_fingerprint(output: str, error_message: str) -> str:
    basis = "\n".join(_quality_lines(output)) or error_message
    return hashlib.sha1(basis[:6000].encode()).hexdigest()[:12]


def _quality_blocker_source_key(project_id: str, fingerprint: str) -> str:
    return source_key(SOURCE_QUALITY, f"baseline:{project_id}:{fingerprint}")


def _quality_blocker_description(
    *,
    project_id: str,
    blocked_task_id: str,
    fingerprint: str,
    error_message: str,
    output: str,
) -> str:
    summary = "\n".join(_quality_lines(output))[:2400]
    parts = [
        "Project baseline quality gate is blocking task execution.",
        "",
        f"Project: {project_id}",
        f"Blocked task: {blocked_task_id}",
        f"Failure fingerprint: {fingerprint}",
        "",
        "Run `st check --quick` in the project, fix the baseline failures, and verify the gate is green.",
        "Do not broaden scope beyond the current baseline quality failures.",
    ]
    if error_message:
        parts.extend(["", "Error:", error_message[:800]])
    if summary:
        parts.extend(["", "Gate summary:", "```", summary, "```"])
    return "\n".join(parts)


def _create_quality_blocker_task(
    *,
    project_id: str,
    blocked_task_id: str,
    fingerprint: str,
    source_key_value: str,
    error_message: str,
    output: str,
) -> str:
    spec = SignalTaskSpec(
        source_key=source_key_value,
        signal_type=SOURCE_QUALITY,
        title=f"Fix baseline quality gate for {project_id}",
        description=_quality_blocker_description(
            project_id=project_id,
            blocked_task_id=blocked_task_id,
            fingerprint=fingerprint,
            error_message=error_message,
            output=output,
        ),
        priority=1,
        task_type=TASK_TYPE_BUG,
        subtask_description=f"Restore green baseline quality gate for {project_id}",
        complexity="STANDARD",
        agent_override=QUALITY_FIX_AGENT,
        source_context={
            BASELINE_QUALITY_MARKER: True,
            "blocked_task_id": blocked_task_id,
            "failure_fingerprint": fingerprint,
            "check_command": "st check --quick",
        },
        steps=[
            {
                "description": "Inspect st check output and referenced .dev-tools detail files to identify the current baseline failures",
            },
            {
                "description": "Fix only the current baseline quality failures without broadening scope",
            },
            {
                "description": "Verify the baseline quality gate is green",
                "spec": {"verify_commands": ["st check --quick"]},
            },
        ],
    )
    return create_signal_task(project_id, spec)


def _block_original_task(task_id: str, blocker_task_id: str) -> None:
    task_dependencies.add_dependency(task_id, blocker_task_id, "blocks")
    message = f"Blocked by baseline quality gate task {blocker_task_id}"
    task_store.update_task(
        task_id,
        status="pending",
        error_message=message,
        claimed_by=None,
        claimed_at=None,
        lock_expires_at=None,
        completed_at=None,
    )
    log_task_event(
        task_id,
        message,
        source="baseline_quality_gate",
        level="warning",
        attributes={"blocker_task_id": blocker_task_id},
    )


def ensure_quality_gate_blocker(
    task_id: str,
    project_id: str,
    *,
    error_message: str,
    output: str = "",
) -> str:
    """Create or reuse a baseline quality blocker task and block *task_id* on it."""
    fingerprint = quality_gate_fingerprint(output, error_message)
    source_key_value = _quality_blocker_source_key(project_id, fingerprint)
    blocker_task_id = task_exists_for_upkeep_source(project_id, source_key_value)
    if not blocker_task_id:
        blocker_task_id = _create_quality_blocker_task(
            project_id=project_id,
            blocked_task_id=task_id,
            fingerprint=fingerprint,
            source_key_value=source_key_value,
            error_message=error_message,
            output=output,
        )
    _block_original_task(task_id, blocker_task_id)
    return blocker_task_id


def is_baseline_quality_gate_task(task_id: str) -> bool:
    spirit = get_task_spirit(task_id)
    context = spirit.get("context") if spirit else None
    upkeep = context.get("upkeep") if isinstance(context, dict) else None
    return isinstance(upkeep, dict) and bool(upkeep.get(BASELINE_QUALITY_MARKER))


def _active_baseline_quality_tasks(project_id: str) -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id,
                t.started_at,
                t.total_sessions,
                t.commits
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status IN ('pending', 'paused', 'failed', 'running')
              AND ts.context -> 'upkeep' ->> %s = 'true'
            """,
            (project_id, BASELINE_QUALITY_MARKER),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "started_at": row[1],
            "total_sessions": row[2],
            "commits": row[3],
        }
        for row in rows
    ]


def _has_work(task: dict[str, Any]) -> bool:
    commits = task.get("commits") or []
    return bool(
        task.get("started_at")
        or int(task.get("total_sessions") or 0) > 0
        or (isinstance(commits, list) and commits)
    )


def clear_project_quality_gate_blockers(project_id: str) -> dict[str, int]:
    """Clear active baseline blockers after the project baseline is green."""
    counts = {"deleted": 0, "completed": 0, "skipped": 0}
    for task in _active_baseline_quality_tasks(project_id):
        task_id = str(task.get("id") or "")
        if not task_id:
            counts["skipped"] += 1
            continue
        if _has_work(task):
            updated = task_store.update_task_status(
                task_id,
                "completed",
                error_message="Baseline quality gate is green.",
                validate_transition=False,
            )
            counts["completed" if updated else "skipped"] += 1
            continue
        deleted = task_store.delete_task(
            task_id,
            deletion_source="baseline-quality:clear",
            deletion_reason="Baseline quality gate is green.",
        )
        counts["deleted" if deleted else "skipped"] += 1
    return counts
