"""Routine upkeep signal discovery and routing.

This module converts existing maintenance signals into normal SummitFlow tasks,
then routes those tasks through the existing autonomous pickup pipeline. It is
not an orchestration layer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import AGENT_HUB_URL
from app.logging_config import get_logger
from app.services._agent_hub_config import build_agent_hub_headers
from app.storage import agent_configs
from app.storage import maintenance_runs as maintenance_store
from app.storage import quality_check_results as qcr_store
from app.storage import tasks as task_store
from app.storage.connection import get_connection, get_cursor
from app.storage.task_spirit import approve_plan, create_task_spirit
from app.tasks.autonomous.refactor_generation import regenerate_refactor_tasks_impl
from app.tasks.autonomous.task_builders import create_single_subtask_with_steps

from .pickup import autonomous_work_pickup

logger = get_logger(__name__)

ROUTINE_UPKEEP_WORKFLOW = "routine_upkeep"
_LOCK_PREFIX = "summitflow:routine-upkeep:"
_FEEDBACK_TIMEOUT_SECONDS = 30.0
_UPKEEP_LABELS = ["routine-upkeep", "auto-generated"]


class RoutineUpkeepSettings(BaseModel):
    """Project-scoped routine upkeep settings."""

    enabled: bool = False
    frequency_minutes: int = Field(default=120, ge=15, le=1440)
    batch_limit: int = Field(default=5, ge=1, le=10)


def get_routine_upkeep_settings(project_id: str) -> RoutineUpkeepSettings:
    """Read routine upkeep settings from the project agent config."""
    config = agent_configs.get_agent_config(project_id)
    return RoutineUpkeepSettings(
        enabled=bool(config.get("upkeep_enabled", False)),
        frequency_minutes=int(config.get("upkeep_frequency_minutes", 120) or 120),
        batch_limit=int(config.get("upkeep_batch_limit", 5) or 5),
    )


def _lock_id(project_id: str) -> int:
    digest = hashlib.sha1(f"{_LOCK_PREFIX}{project_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def _routine_upkeep_lock(project_id: str) -> Iterator[bool]:
    """Try to acquire the project upkeep advisory lock without waiting."""
    lock_id = _lock_id(project_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
        row = cur.fetchone()
        acquired = bool(row and row[0])
        try:
            yield acquired
        finally:
            if acquired:
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
            conn.commit()


def _latest_upkeep_run(project_id: str) -> dict[str, Any] | None:
    runs = maintenance_store.list_maintenance_runs(
        limit=1,
        workflow_name=ROUTINE_UPKEEP_WORKFLOW,
        project_id=project_id,
    )
    return runs[0] if runs else None


def _is_due(
    project_id: str,
    settings: RoutineUpkeepSettings,
    *,
    now: datetime | None = None,
) -> bool:
    latest = _latest_upkeep_run(project_id)
    if not latest:
        return True
    started_at = latest.get("started_at")
    if not isinstance(started_at, datetime):
        return True
    current = now or datetime.now(started_at.tzinfo or UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return current - started_at >= timedelta(minutes=settings.frequency_minutes)


def _record_run(
    status: str,
    started_at: datetime,
    result: dict[str, Any],
    *,
    error_message: str | None = None,
) -> None:
    finished_at = datetime.now(UTC)
    maintenance_store.record_maintenance_run(
        ROUTINE_UPKEEP_WORKFLOW,
        status,
        started_at=started_at,
        finished_at=finished_at,
        rows_cleaned=int(result.get("tasks_created", 0) or 0),
        summary=result,
        error_message=error_message,
    )


def task_exists_for_upkeep_source(project_id: str, source_key: str) -> str | None:
    """Return active task ID for an upkeep source key, if one exists."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status NOT IN ('completed', 'cancelled')
              AND ts.context -> 'upkeep' ->> 'source_key' = %s
            ORDER BY t.created_at ASC
            LIMIT 1
            """,
            (project_id, source_key),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _source_key(signal_type: str, stable_id: object) -> str:
    return f"upkeep:{signal_type}:{stable_id}"


def _normalize_quality_key_part(value: object, default: str) -> str:
    text = str(value or "").strip()
    if not text or text in {"-", "unknown", "None", "null"}:
        return default
    return text


def _quality_source_key(result: dict[str, Any]) -> str | None:
    """Build a stable source key for actionable quality failures."""
    check_type = _normalize_quality_key_part(result.get("check_type"), "quality")
    check_name = _normalize_quality_key_part(result.get("check_name"), "unknown")
    file_path = _normalize_quality_key_part(result.get("file_path"), "project")
    line_number = _normalize_quality_key_part(result.get("line_number"), "any")

    if file_path != "project":
        return _source_key("quality", f"{check_type}:{check_name}:{file_path}:{line_number}")

    error_message = str(result.get("error_message") or "").strip()
    if not error_message:
        return None
    digest = hashlib.sha1(error_message[:2000].encode()).hexdigest()[:12]
    return _source_key("quality", f"{check_type}:{check_name}:project:{digest}")


def _files_to_modify_from_result(result: dict[str, Any]) -> list[str]:
    file_path = result.get("file_path")
    return [str(file_path)] if isinstance(file_path, str) and file_path else []


def _list_unfixed_quality_results(project_id: str, limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return qcr_store.list_check_results(
            conn,
            project_id,
            status="fail",
            unfixed_only=True,
            limit=limit,
        )


def _mark_quality_escalated(result_id: int, task_id: str) -> None:
    with get_connection() as conn:
        qcr_store.mark_escalated(conn, result_id, task_id)
        conn.commit()


def _quality_title(result: dict[str, Any]) -> str:
    check_type = str(result.get("check_type") or "quality")
    check_name = str(result.get("check_name") or "failure")
    file_path = str(result.get("file_path") or "project")
    line_number = result.get("line_number")
    location = f"{file_path}:{line_number}" if line_number else file_path
    return f"Fix: {check_type} {check_name} in {location}"


def _quality_description(result: dict[str, Any]) -> str:
    parts = [
        "Routine upkeep found an unfixed quality failure.",
        "",
        f"Check type: {result.get('check_type') or 'quality'}",
        f"Check name: {result.get('check_name') or 'unknown'}",
        f"File: {result.get('file_path') or 'unknown'}",
        f"Quality result ID: {result.get('id')}",
    ]
    if result.get("line_number"):
        parts.append(f"Line: {result['line_number']}")
    if result.get("error_message"):
        parts.extend(["", "Error:", "```", str(result["error_message"])[:1200], "```"])
    return "\n".join(parts)


def _create_signal_task(
    *,
    project_id: str,
    source_key: str,
    signal_type: str,
    title: str,
    description: str,
    priority: int,
    task_type: str,
    complexity: str = "SIMPLE",
    files_to_modify: list[str] | None = None,
    subtask_description: str,
    source_context: dict[str, Any] | None = None,
) -> str:
    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        complexity=complexity,
        execution_mode="autonomous",
        autonomous=True,
        labels=[*_UPKEEP_LABELS, signal_type],
    )
    task_id = str(task["id"])
    context: dict[str, Any] = {
        "upkeep": {
            "source_key": source_key,
            "signal_type": signal_type,
        },
    }
    if source_context:
        context["upkeep"].update(source_context)
    if files_to_modify:
        context["files_to_modify"] = files_to_modify
    create_task_spirit(
        task_id=task_id,
        done_when=[
            "The underlying upkeep signal is resolved or explicitly marked obsolete with evidence",
            "Relevant targeted checks pass through dt",
            "No unrelated behavior changes are introduced",
        ],
        context=context,
        complexity=complexity,
    )
    approve_plan(task_id, approved_by="routine-upkeep")
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id="1.1",
        phase="backend" if files_to_modify and any(path.endswith(".py") for path in files_to_modify) else "implementation",
        description=subtask_description,
        subtask_type="bug-fix" if task_type == "bug" else "implementation",
    )
    return task_id


def _create_quality_failure_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous bug tasks for unfixed quality failures."""
    created: list[str] = []
    for result in _list_unfixed_quality_results(project_id, limit):
        result_id = result.get("id")
        if result_id is None:
            continue
        try:
            result_id_int = int(result_id)
        except (TypeError, ValueError):
            logger.warning("routine_upkeep_quality_result_without_numeric_id", result_id=result_id)
            continue
        if result.get("escalation_task_id"):
            continue
        source_key = _quality_source_key(result)
        if source_key is None:
            logger.info("routine_upkeep_skipping_unactionable_quality_result", result_id=result_id_int)
            continue
        if task_exists_for_upkeep_source(project_id, source_key):
            continue
        task_id = _create_signal_task(
            project_id=project_id,
            source_key=source_key,
            signal_type="quality",
            title=_quality_title(result),
            description=_quality_description(result),
            priority=2,
            task_type="bug",
            complexity="SIMPLE",
            files_to_modify=_files_to_modify_from_result(result),
            subtask_description=f"Resolve quality failure {result_id_int}",
            source_context={"quality_result_id": result_id_int},
        )
        _mark_quality_escalated(result_id_int, task_id)
        created.append(task_id)
        if len(created) >= limit:
            break
    return created


def _fetch_feedback_items(project_id: str, limit: int) -> list[dict[str, Any]]:
    """Fetch active, unlinked Agent Hub feedback for the project."""
    params = {
        "project_id": project_id,
        "status": "active",
        "sort": "votes",
        "limit": limit,
    }
    with httpx.Client(timeout=_FEEDBACK_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{AGENT_HUB_URL}/api/feedback",
            params=params,
            headers=build_agent_hub_headers(
                request_source="sf-routine-upkeep",
                extra_headers={
                    "X-Source-Client": "summitflow",
                    "X-Tool-Name": "routine-upkeep",
                },
            ),
        )
        response.raise_for_status()
        payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _link_feedback_task(feedback_id: str, task_id: str) -> None:
    with httpx.Client(timeout=_FEEDBACK_TIMEOUT_SECONDS) as client:
        response = client.patch(
            f"{AGENT_HUB_URL}/api/feedback/{feedback_id}",
            json={"linked_task_id": task_id},
            headers=build_agent_hub_headers(
                request_source="sf-routine-upkeep",
                extra_headers={
                    "X-Source-Client": "summitflow",
                    "X-Tool-Name": "routine-upkeep",
                },
            ),
        )
        response.raise_for_status()


def _feedback_task_type(feedback: dict[str, Any]) -> str | None:
    feedback_type = feedback.get("feedback_type")
    if feedback_type == "praise":
        return None
    if feedback_type == "friction":
        return "bug"
    return "task"


def _feedback_description(feedback: dict[str, Any]) -> str:
    parts = [
        "Routine upkeep selected this active feedback item for resolution.",
        "",
        f"Feedback ID: {feedback.get('id')}",
        f"Component: {feedback.get('component_id') or 'unknown'}",
        f"Type: {feedback.get('feedback_type') or 'unknown'}",
        f"Votes: {feedback.get('vote_count') or 0}",
    ]
    if feedback.get("description"):
        parts.extend(["", str(feedback["description"])[:1200]])
    return "\n".join(parts)


def _create_feedback_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous tasks for top active feedback items."""
    created: list[str] = []
    for feedback in _fetch_feedback_items(project_id, limit):
        feedback_id = feedback.get("id")
        if not feedback_id or feedback.get("linked_task_id"):
            continue
        task_type = _feedback_task_type(feedback)
        if task_type is None:
            continue
        source_key = _source_key("feedback", feedback_id)
        if task_exists_for_upkeep_source(project_id, source_key):
            continue
        task_id = _create_signal_task(
            project_id=project_id,
            source_key=source_key,
            signal_type="feedback",
            title=f"Handle feedback: {feedback.get('title') or feedback_id}",
            description=_feedback_description(feedback),
            priority=2 if task_type == "bug" else 3,
            task_type=task_type,
            subtask_description=f"Resolve feedback item {feedback_id}",
        )
        try:
            _link_feedback_task(str(feedback_id), task_id)
        except Exception as exc:
            logger.warning(
                "feedback_link_failed",
                feedback_id=feedback_id,
                task_id=task_id,
                error=str(exc),
            )
        created.append(task_id)
        if len(created) >= limit:
            break
    return created


def _remaining_capacity(settings: RoutineUpkeepSettings, budget: int, tasks_created: int) -> int:
    return max(0, min(settings.batch_limit, budget) - tasks_created)


def _daily_budget_remaining(project_id: str, settings: RoutineUpkeepSettings) -> int:
    max_tasks = agent_configs.get_max_tasks_per_day(project_id)
    if max_tasks is None:
        return settings.batch_limit
    completed_today = task_store.count_completed_tasks_today(project_id)
    return max(0, min(settings.batch_limit, max_tasks - completed_today))


def _run_refactor_source(project_id: str, create_limit: int) -> dict[str, Any]:
    return regenerate_refactor_tasks_impl(project_id, create_limit=create_limit)


def _safe_source(name: str, fn: Callable[[], Any]) -> tuple[Any, str | None]:
    try:
        return fn(), None
    except Exception as exc:
        logger.warning("routine_upkeep_source_failed", source=name, error=str(exc))
        return None, str(exc)


def run_routine_upkeep(
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run one routine upkeep discovery and routing cycle."""
    started_at = datetime.now(UTC)
    settings = get_routine_upkeep_settings(project_id)
    if not settings.enabled:
        return {
            "project_id": project_id,
            "status": "disabled",
            "tasks_created": 0,
            "dispatch": {"dispatched": 0},
        }
    if not force and not _is_due(project_id, settings):
        return {
            "project_id": project_id,
            "status": "skipped",
            "reason": "not_due",
            "tasks_created": 0,
            "dispatch": {"dispatched": 0},
        }

    with _routine_upkeep_lock(project_id) as acquired:
        if not acquired:
            result = {
                "project_id": project_id,
                "status": "blocked",
                "reason": "already_running",
                "tasks_created": 0,
                "dispatch": {"dispatched": 0},
                "outcome": "blocked",
            }
            _record_run("blocked", started_at, result)
            return result

        source_errors: dict[str, str] = {}
        created_task_ids: list[str] = []
        budget = _daily_budget_remaining(project_id, settings)

        remaining = _remaining_capacity(settings, budget, len(created_task_ids))
        refactor_result, error = _safe_source(
            "refactors",
            lambda: _run_refactor_source(project_id, remaining),
        )
        if error:
            source_errors["refactors"] = error
        refactor_created = (
            int(refactor_result.get("created_count", 0))
            if isinstance(refactor_result, dict)
            else 0
        )

        remaining = _remaining_capacity(settings, budget, len(created_task_ids) + refactor_created)
        quality_task_ids: list[str] = []
        if remaining > 0:
            quality_task_ids, error = _safe_source(
                "quality",
                lambda: _create_quality_failure_tasks(project_id, remaining),
            )
            if error:
                source_errors["quality"] = error
            elif quality_task_ids:
                created_task_ids.extend(quality_task_ids)

        remaining = _remaining_capacity(settings, budget, len(created_task_ids) + refactor_created)
        feedback_task_ids: list[str] = []
        if remaining > 0:
            feedback_task_ids, error = _safe_source(
                "feedback",
                lambda: _create_feedback_tasks(project_id, remaining),
            )
            if error:
                source_errors["feedback"] = error
            elif feedback_task_ids:
                created_task_ids.extend(feedback_task_ids)

        dispatch_result: dict[str, Any]
        if dispatch is None:
            dispatch_result = {"dispatched": 0, "message": "dispatch not configured"}
        else:
            dispatch_result = dict(
                autonomous_work_pickup(
                    project_id,
                    dispatch=dispatch,
                    limit=settings.batch_limit,
                )
            )

        created_count = len(created_task_ids)
        total_created = created_count + refactor_created
        status = "completed"
        if source_errors and total_created == 0 and int(dispatch_result.get("dispatched", 0) or 0) == 0:
            status = "failed"
        if dispatch_result.get("status") in {"disabled", "unhealthy", "daily_limit", "concurrency_limit"}:
            status = "failed"
            source_errors["dispatch"] = str(dispatch_result.get("reason") or dispatch_result.get("status"))

        result = {
            "project_id": project_id,
            "status": status,
            "outcome": status,
            "settings": settings.model_dump(),
            "tasks_created": total_created,
            "created_task_ids": created_task_ids,
            "sources": {
                "refactors": refactor_result or {},
                "quality": {"created_task_ids": quality_task_ids},
                "feedback": {"created_task_ids": feedback_task_ids},
            },
            "source_errors": source_errors,
            "dispatch": dispatch_result,
        }
        _record_run(status, started_at, result)
        return result
