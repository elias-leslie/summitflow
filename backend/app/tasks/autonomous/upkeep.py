"""Routine upkeep signal discovery and routing.

This module converts existing maintenance signals into normal SummitFlow tasks,
then routes those tasks through existing autonomous pickup pipeline. It is
not orchestration layer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.logging_config import get_logger
from app.storage import agent_configs
from app.storage import maintenance_runs as maintenance_store
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.tasks.autonomous.refactor_generation import regenerate_refactor_tasks_impl

from .pickup import autonomous_work_pickup
from .upkeep_constants import (
    DISPATCH_FAILURE_STATUSES,
    LOCK_PREFIX,
    REASON_ALREADY_RUNNING,
    REASON_NOT_DUE,
    ROUTINE_UPKEEP_WORKFLOW,
    SOURCE_FEEDBACK,
    SOURCE_QUALITY,
    SOURCE_REFACTORS,
    SOURCES,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_DISABLED,
    STATUS_FAILED,
    STATUS_SKIPPED,
)
from .upkeep_feedback import create_feedback_tasks as _create_feedback_tasks
from .upkeep_models import RunAccumulator, RunOutcome, SourceRunResult
from .upkeep_quality import create_quality_failure_tasks as _create_quality_failure_tasks
from .upkeep_signals import task_exists_for_upkeep_source

logger = get_logger(__name__)

__all__ = ["RoutineUpkeepSettings", "get_routine_upkeep_settings", "run_routine_upkeep", "task_exists_for_upkeep_source"]


class RoutineUpkeepSettings(BaseModel):
    """Project-scoped routine upkeep settings."""

    enabled: bool = False
    frequency_minutes: int = Field(default=120, ge=15, le=1440)
    batch_limit: int = Field(default=5, ge=1, le=10)


def get_routine_upkeep_settings(project_id: str) -> RoutineUpkeepSettings:
    """Read routine upkeep settings from project agent config."""
    config = agent_configs.get_agent_config(project_id)
    return RoutineUpkeepSettings(
        enabled=bool(config.get("upkeep_enabled", False)),
        frequency_minutes=int(config.get("upkeep_frequency_minutes", 120) or 120),
        batch_limit=int(config.get("upkeep_batch_limit", 5) or 5),
    )


def _lock_id(project_id: str) -> int:
    digest = hashlib.sha1(f"{LOCK_PREFIX}{project_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def _routine_upkeep_lock(project_id: str) -> Iterator[bool]:
    """Try to acquire project upkeep advisory lock without waiting."""
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
    maintenance_store.record_maintenance_run(
        ROUTINE_UPKEEP_WORKFLOW,
        status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_cleaned=int(result.get("tasks_created", 0) or 0),
        summary=result,
        error_message=error_message,
    )


def _upkeep_result(
    project_id: str,
    status: str,
    *,
    tasks_created: int = 0,
    dispatch: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "project_id": project_id,
        "status": status,
        "tasks_created": tasks_created,
        "dispatch": dispatch or {"dispatched": 0},
    }
    result.update(extra)
    return result


def _blocked_result(project_id: str) -> dict[str, Any]:
    return _upkeep_result(
        project_id,
        STATUS_BLOCKED,
        reason=REASON_ALREADY_RUNNING,
        outcome=STATUS_BLOCKED,
    )


def _safe_source(name: str, fn: Callable[[], Any]) -> SourceRunResult:
    try:
        return SourceRunResult(payload=fn())
    except Exception as exc:
        logger.warning("routine_upkeep_source_failed", source=name, error=str(exc))
        return SourceRunResult(error=str(exc))


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


def _source_plan(project_id: str, remaining: int) -> dict[str, Callable[[], Any]]:
    return {
        SOURCE_REFACTORS: lambda: _run_refactor_source(project_id, remaining),
        SOURCE_QUALITY: lambda: _create_quality_failure_tasks(project_id, remaining),
        SOURCE_FEEDBACK: lambda: _create_feedback_tasks(project_id, remaining),
    }


def _apply_source_result(run: RunAccumulator, source_name: str, source_result: SourceRunResult) -> None:
    if source_result.error:
        run.source_errors[source_name] = source_result.error
        return
    if source_name == SOURCE_REFACTORS:
        payload = source_result.payload or {}
        run.source_payloads[source_name] = payload
        run.refactor_created = int(payload.get("created_count", 0) or 0)
        return
    created = list(source_result.payload or [])
    run.source_payloads[source_name] = {"created_task_ids": created}
    run.created_task_ids.extend(created)


def _run_sources(project_id: str, settings: RoutineUpkeepSettings) -> RunOutcome:
    budget = _daily_budget_remaining(project_id, settings)
    run = RunAccumulator()
    for source_name in SOURCES:
        remaining = _remaining_capacity(settings, budget, len(run.created_task_ids) + run.refactor_created)
        if remaining <= 0:
            break
        source_result = _safe_source(source_name, _source_plan(project_id, remaining)[source_name])
        _apply_source_result(run, source_name, source_result)
    return RunOutcome(
        source_payloads=run.source_payloads,
        source_errors=run.source_errors,
        created_task_ids=run.created_task_ids,
    )


def _dispatch_result(
    project_id: str,
    settings: RoutineUpkeepSettings,
    dispatch: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    if dispatch is None:
        return {"dispatched": 0, "message": "dispatch not configured"}
    return dict(autonomous_work_pickup(project_id, dispatch=dispatch, limit=settings.batch_limit))


def _result_status(
    source_errors: dict[str, str],
    tasks_created: int,
    dispatch_result: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    errors = dict(source_errors)
    status = STATUS_COMPLETED
    if errors and tasks_created == 0 and int(dispatch_result.get("dispatched", 0) or 0) == 0:
        status = STATUS_FAILED
    dispatch_status = dispatch_result.get("status")
    if dispatch_status in DISPATCH_FAILURE_STATUSES:
        status = STATUS_FAILED
        errors["dispatch"] = str(dispatch_result.get("reason") or dispatch_status)
    return status, errors


def _build_run_result(
    project_id: str,
    settings: RoutineUpkeepSettings,
    run: RunOutcome,
    dispatch_result: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    total_created = len(run.created_task_ids) + int(run.source_payloads[SOURCE_REFACTORS].get("created_count", 0) or 0)
    status, errors = _result_status(run.source_errors, total_created, dispatch_result)
    return status, {
        "project_id": project_id,
        "status": status,
        "outcome": status,
        "settings": settings.model_dump(),
        "tasks_created": total_created,
        "created_task_ids": run.created_task_ids,
        "sources": run.source_payloads,
        "source_errors": errors,
        "dispatch": dispatch_result,
    }


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
        return _upkeep_result(project_id, STATUS_DISABLED)
    if not force and not _is_due(project_id, settings):
        return _upkeep_result(project_id, STATUS_SKIPPED, reason=REASON_NOT_DUE)

    with _routine_upkeep_lock(project_id) as acquired:
        if not acquired:
            result = _blocked_result(project_id)
            _record_run(STATUS_BLOCKED, started_at, result)
            return result

        run = _run_sources(project_id, settings)
        dispatch_result = _dispatch_result(project_id, settings, dispatch)
        status, result = _build_run_result(project_id, settings, run, dispatch_result)
        _record_run(status, started_at, result)
        return result
