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
_REQUEST_SOURCE = "sf-routine-upkeep"
_SOURCE_CLIENT = "summitflow"
_TOOL_NAME = "routine-upkeep"
_SOURCE_QUALITY = "quality"
_SOURCE_FEEDBACK = "feedback"
_SOURCE_REFACTORS = "refactors"
_SOURCES = (_SOURCE_REFACTORS, _SOURCE_QUALITY, _SOURCE_FEEDBACK)
_STATUS_ACTIVE = "active"
_STATUS_COMPLETED = "completed"
_STATUS_DISABLED = "disabled"
_STATUS_SKIPPED = "skipped"
_STATUS_BLOCKED = "blocked"
_STATUS_FAILED = "failed"
_SORT_VOTES = "votes"
_TASK_TYPE_BUG = "bug"
_TASK_TYPE_TASK = "task"
_COMPLEXITY_SIMPLE = "SIMPLE"
_EXECUTION_MODE_AUTONOMOUS = "autonomous"
_SUBTASK_ID = "1.1"
_SUBTASK_TYPE_IMPLEMENTATION = "implementation"
_SUBTASK_TYPE_BUG_FIX = "bug-fix"
_PHASE_BACKEND = "backend"
_PHASE_IMPLEMENTATION = "implementation"
_REASON_NOT_DUE = "not_due"
_REASON_ALREADY_RUNNING = "already_running"
_DISPATCH_FAILURE_STATUSES = {"disabled", "unhealthy", "daily_limit", "concurrency_limit"}
_FINISHED_TASK_STATUSES = (_STATUS_COMPLETED, "cancelled")
_QUALITY_DEFAULTS = {
    "check_type": _SOURCE_QUALITY,
    "check_name": "unknown",
    "file_path": "project",
    "line_number": "any",
}
_EMPTY_KEY_PARTS = {"-", "unknown", "None", "null"}
_DONE_WHEN = [
    "The underlying upkeep signal is resolved or explicitly marked obsolete with evidence",
    "Relevant targeted checks pass through st check",
    "No unrelated behavior changes are introduced",
]


class RoutineUpkeepSettings(BaseModel):
    """Project-scoped routine upkeep settings."""

    enabled: bool = False
    frequency_minutes: int = Field(default=120, ge=15, le=1440)
    batch_limit: int = Field(default=5, ge=1, le=10)


class _SourceRunResult(BaseModel):
    payload: Any = None
    error: str | None = None


class _CreatedSignalTask(BaseModel):
    task_id: str
    source_key: str


class _SignalTaskSpec(BaseModel):
    source_key: str
    signal_type: str
    title: str
    description: str
    priority: int
    task_type: str
    subtask_description: str
    complexity: str = _COMPLEXITY_SIMPLE
    files_to_modify: list[str] | None = None
    source_context: dict[str, Any] | None = None


class _RunAccumulator(BaseModel):
    source_payloads: dict[str, Any] = Field(
        default_factory=lambda: {
            _SOURCE_REFACTORS: {},
            _SOURCE_QUALITY: {"created_task_ids": []},
            _SOURCE_FEEDBACK: {"created_task_ids": []},
        }
    )
    source_errors: dict[str, str] = Field(default_factory=dict)
    created_task_ids: list[str] = Field(default_factory=list)
    refactor_created: int = 0


class _RunOutcome(BaseModel):
    source_payloads: dict[str, Any]
    source_errors: dict[str, str]
    created_task_ids: list[str]


def get_routine_upkeep_settings(project_id: str) -> RoutineUpkeepSettings:
    """Read routine upkeep settings from project agent config."""
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


def _agent_hub_headers() -> dict[str, str]:
    return build_agent_hub_headers(
        request_source=_REQUEST_SOURCE,
        extra_headers={
            "X-Source-Client": _SOURCE_CLIENT,
            "X-Tool-Name": _TOOL_NAME,
        },
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
        _STATUS_BLOCKED,
        reason=_REASON_ALREADY_RUNNING,
        outcome=_STATUS_BLOCKED,
    )


def task_exists_for_upkeep_source(project_id: str, source_key: str) -> str | None:
    """Return active task ID for upkeep source key, if one exists."""
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
    return default if not text or text in _EMPTY_KEY_PARTS else text


def _quality_source_key(result: dict[str, Any]) -> str | None:
    """Build stable source key for actionable quality failures."""
    parts = {
        key: _normalize_quality_key_part(result.get(key), default)
        for key, default in _QUALITY_DEFAULTS.items()
    }
    if parts["file_path"] != _QUALITY_DEFAULTS["file_path"]:
        stable_id = f"{parts['check_type']}:{parts['check_name']}:{parts['file_path']}:{parts['line_number']}"
        return _source_key(_SOURCE_QUALITY, stable_id)
    error_message = str(result.get("error_message") or "").strip()
    if not error_message:
        return None
    digest = hashlib.sha1(error_message[:2000].encode()).hexdigest()[:12]
    stable_id = f"{parts['check_type']}:{parts['check_name']}:project:{digest}"
    return _source_key(_SOURCE_QUALITY, stable_id)


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


def _quality_task_spec(result: dict[str, Any], result_id: int, source_key: str) -> _SignalTaskSpec:
    check_type = str(result.get("check_type") or _QUALITY_DEFAULTS["check_type"])
    check_name = str(result.get("check_name") or "failure")
    file_path = str(result.get("file_path") or _QUALITY_DEFAULTS["file_path"])
    line_number = result.get("line_number")
    location = f"{file_path}:{line_number}" if line_number else file_path
    parts = [
        "Routine upkeep found an unfixed quality failure.",
        "",
        f"Check type: {result.get('check_type') or _QUALITY_DEFAULTS['check_type']}",
        f"Check name: {result.get('check_name') or _QUALITY_DEFAULTS['check_name']}",
        f"File: {result.get('file_path') or _QUALITY_DEFAULTS['check_name']}",
        f"Quality result ID: {result_id}",
    ]
    if line_number:
        parts.append(f"Line: {line_number}")
    if result.get("error_message"):
        parts.extend(["", "Error:", "```", str(result["error_message"])[:1200], "```"])
    return _SignalTaskSpec(
        source_key=source_key,
        signal_type=_SOURCE_QUALITY,
        title=f"Fix: {check_type} {check_name} in {location}",
        description="\n".join(parts),
        priority=2,
        task_type=_TASK_TYPE_BUG,
        files_to_modify=_files_to_modify_from_result(result),
        subtask_description=f"Resolve quality failure {result_id}",
        source_context={"quality_result_id": result_id},
    )


def _feedback_task_type(feedback: dict[str, Any]) -> str | None:
    feedback_type = feedback.get("feedback_type")
    if feedback_type == "praise":
        return None
    return _TASK_TYPE_BUG if feedback_type == "friction" else _TASK_TYPE_TASK


def _fetch_feedback_items(project_id: str, limit: int) -> list[dict[str, Any]]:
    """Fetch active, unlinked Agent Hub feedback for project."""
    with httpx.Client(timeout=_FEEDBACK_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{AGENT_HUB_URL}/api/feedback",
            params={
                "project_id": project_id,
                "status": _STATUS_ACTIVE,
                "sort": _SORT_VOTES,
                "limit": limit,
            },
            headers=_agent_hub_headers(),
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
            headers=_agent_hub_headers(),
        )
        response.raise_for_status()


def _feedback_task_spec(feedback: dict[str, Any], task_type: str, source_key: str) -> _SignalTaskSpec:
    feedback_id = feedback.get("id")
    parts = [
        "Routine upkeep selected this active feedback item for resolution.",
        "",
        f"Feedback ID: {feedback_id}",
        f"Component: {feedback.get('component_id') or 'unknown'}",
        f"Type: {feedback.get('feedback_type') or 'unknown'}",
        f"Votes: {feedback.get('vote_count') or 0}",
    ]
    if feedback.get("description"):
        parts.extend(["", str(feedback["description"])[:1200]])
    return _SignalTaskSpec(
        source_key=source_key,
        signal_type=_SOURCE_FEEDBACK,
        title=f"Handle feedback: {feedback.get('title') or feedback_id}",
        description="\n".join(parts),
        priority=2 if task_type == _TASK_TYPE_BUG else 3,
        task_type=task_type,
        subtask_description=f"Resolve feedback item {feedback_id}",
    )


def _signal_context(
    source_key: str,
    signal_type: str,
    *,
    files_to_modify: list[str] | None,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"upkeep": {"source_key": source_key, "signal_type": signal_type}}
    if source_context:
        context["upkeep"].update(source_context)
    if files_to_modify:
        context["files_to_modify"] = files_to_modify
    return context


def _subtask_phase(files_to_modify: list[str] | None) -> str:
    if files_to_modify and any(path.endswith(".py") for path in files_to_modify):
        return _PHASE_BACKEND
    return _PHASE_IMPLEMENTATION


def _create_signal_task(project_id: str, spec: _SignalTaskSpec) -> str:
    task = task_store.create_task(
        project_id=project_id,
        title=spec.title,
        description=spec.description,
        priority=spec.priority,
        task_type=spec.task_type,
        complexity=spec.complexity,
        execution_mode=_EXECUTION_MODE_AUTONOMOUS,
        autonomous=True,
        labels=[*_UPKEEP_LABELS, spec.signal_type],
    )
    task_id = str(task["id"])
    create_task_spirit(
        task_id=task_id,
        done_when=_DONE_WHEN,
        context=_signal_context(
            spec.source_key,
            spec.signal_type,
            files_to_modify=spec.files_to_modify,
            source_context=spec.source_context,
        ),
        complexity=spec.complexity,
    )
    approve_plan(task_id, approved_by="routine-upkeep")
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id=_SUBTASK_ID,
        phase=_subtask_phase(spec.files_to_modify),
        description=spec.subtask_description,
        subtask_type=_SUBTASK_TYPE_BUG_FIX if spec.task_type == _TASK_TYPE_BUG else _SUBTASK_TYPE_IMPLEMENTATION,
    )
    return task_id


def _safe_source(name: str, fn: Callable[[], Any]) -> _SourceRunResult:
    try:
        return _SourceRunResult(payload=fn())
    except Exception as exc:
        logger.warning("routine_upkeep_source_failed", source=name, error=str(exc))
        return _SourceRunResult(error=str(exc))


def _coerce_result_id(result_id: object) -> int | None:
    if result_id is None:
        return None
    if isinstance(result_id, bool):
        logger.warning("routine_upkeep_quality_result_without_numeric_id", result_id=result_id)
        return None
    if isinstance(result_id, int):
        return result_id
    if isinstance(result_id, str):
        try:
            return int(result_id)
        except ValueError:
            logger.warning("routine_upkeep_quality_result_without_numeric_id", result_id=result_id)
            return None
    logger.warning("routine_upkeep_quality_result_without_numeric_id", result_id=result_id)
    return None


def _quality_task_from_result(project_id: str, result: dict[str, Any]) -> _CreatedSignalTask | None:
    result_id = _coerce_result_id(result.get("id"))
    if result_id is None or result.get("escalation_task_id"):
        return None
    source_key = _quality_source_key(result)
    if source_key is None:
        logger.info("routine_upkeep_skipping_unactionable_quality_result", result_id=result_id)
        return None
    if task_exists_for_upkeep_source(project_id, source_key):
        return None
    task_id = _create_signal_task(project_id, _quality_task_spec(result, result_id, source_key))
    _mark_quality_escalated(result_id, task_id)
    return _CreatedSignalTask(task_id=task_id, source_key=source_key)


def _create_quality_failure_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous bug tasks for unfixed quality failures."""
    created: list[str] = []
    for result in _list_unfixed_quality_results(project_id, limit):
        created_task = _quality_task_from_result(project_id, result)
        if created_task is None:
            continue
        created.append(created_task.task_id)
        if len(created) >= limit:
            break
    return created


def _feedback_task_from_item(project_id: str, feedback: dict[str, Any]) -> _CreatedSignalTask | None:
    feedback_id = feedback.get("id")
    if not feedback_id or feedback.get("linked_task_id"):
        return None
    task_type = _feedback_task_type(feedback)
    if task_type is None:
        return None
    source_key = _source_key(_SOURCE_FEEDBACK, feedback_id)
    if task_exists_for_upkeep_source(project_id, source_key):
        return None
    task_id = _create_signal_task(project_id, _feedback_task_spec(feedback, task_type, source_key))
    try:
        _link_feedback_task(str(feedback_id), task_id)
    except Exception as exc:
        logger.warning("feedback_link_failed", feedback_id=feedback_id, task_id=task_id, error=str(exc))
    return _CreatedSignalTask(task_id=task_id, source_key=source_key)


def _create_feedback_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous tasks for top active feedback items."""
    created: list[str] = []
    for feedback in _fetch_feedback_items(project_id, limit):
        created_task = _feedback_task_from_item(project_id, feedback)
        if created_task is None:
            continue
        created.append(created_task.task_id)
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


def _source_plan(project_id: str, remaining: int) -> dict[str, Callable[[], Any]]:
    return {
        _SOURCE_REFACTORS: lambda: _run_refactor_source(project_id, remaining),
        _SOURCE_QUALITY: lambda: _create_quality_failure_tasks(project_id, remaining),
        _SOURCE_FEEDBACK: lambda: _create_feedback_tasks(project_id, remaining),
    }


def _apply_source_result(run: _RunAccumulator, source_name: str, source_result: _SourceRunResult) -> None:
    if source_result.error:
        run.source_errors[source_name] = source_result.error
        return
    if source_name == _SOURCE_REFACTORS:
        payload = source_result.payload or {}
        run.source_payloads[source_name] = payload
        run.refactor_created = int(payload.get("created_count", 0) or 0)
        return
    created = list(source_result.payload or [])
    run.source_payloads[source_name] = {"created_task_ids": created}
    run.created_task_ids.extend(created)


def _run_sources(project_id: str, settings: RoutineUpkeepSettings) -> _RunOutcome:
    budget = _daily_budget_remaining(project_id, settings)
    run = _RunAccumulator()
    for source_name in _SOURCES:
        remaining = _remaining_capacity(settings, budget, len(run.created_task_ids) + run.refactor_created)
        if remaining <= 0:
            break
        source_result = _safe_source(source_name, _source_plan(project_id, remaining)[source_name])
        _apply_source_result(run, source_name, source_result)
    return _RunOutcome(
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
    status = _STATUS_COMPLETED
    if errors and tasks_created == 0 and int(dispatch_result.get("dispatched", 0) or 0) == 0:
        status = _STATUS_FAILED
    dispatch_status = dispatch_result.get("status")
    if dispatch_status in _DISPATCH_FAILURE_STATUSES:
        status = _STATUS_FAILED
        errors["dispatch"] = str(dispatch_result.get("reason") or dispatch_status)
    return status, errors


def _build_run_result(
    project_id: str,
    settings: RoutineUpkeepSettings,
    run: _RunOutcome,
    dispatch_result: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    total_created = len(run.created_task_ids) + int(run.source_payloads[_SOURCE_REFACTORS].get("created_count", 0) or 0)
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
        return _upkeep_result(project_id, _STATUS_DISABLED)
    if not force and not _is_due(project_id, settings):
        return _upkeep_result(project_id, _STATUS_SKIPPED, reason=_REASON_NOT_DUE)

    with _routine_upkeep_lock(project_id) as acquired:
        if not acquired:
            result = _blocked_result(project_id)
            _record_run(_STATUS_BLOCKED, started_at, result)
            return result

        run = _run_sources(project_id, settings)
        dispatch_result = _dispatch_result(project_id, settings, dispatch)
        status, result = _build_run_result(project_id, settings, run, dispatch_result)
        _record_run(status, started_at, result)
        return result
