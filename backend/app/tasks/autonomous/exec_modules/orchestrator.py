from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ....config import AGENT_HUB_URL
from ....core.debug import debug_section
from ....logging_config import get_logger
from ....services._agent_hub_config import build_agent_hub_headers
from ....services.task_checkout import get_task_checkout
from ....services.task_lane_preflight import check_task_lane_conflicts
from ....storage import tasks as task_store
from ....storage.subtasks import get_subtasks_for_task
from .agent_execution import execute_agent_feedback
from .checkout import check_main_repo_leakage
from .checkout_setup import setup_task_checkout
from .completion_handler import (
    handle_early_completion,
    handle_failed_execution,
    handle_partial_completion,
    handle_successful_completion,
)
from .events import emit_error, emit_log, emit_progress
from .execution_loop import execute_subtask_loop
from .orchestrator_execution import execute_task_locked_impl, handle_completion, load_subtasks
from .orchestrator_lanes import (
    maybe_reclaim_same_task_lane,
    same_task_lane_guard_result,
    session_ready_for_reclaim,
)
from .orchestrator_preparation import (
    active_task_checkpoint,
    prepare_completed_task_closeout,
    prepare_execution,
)
from .pristine_validation import validate_pristine_codebase

logger = get_logger(__name__)

_SESSION_TIMEOUT_SECONDS = 10.0
_FINAL_SESSION_STATUSES = {"completed", "failed", "error", "closed", "cancelled"}
_FINAL_SESSION_HEALTH = {"completed", "failed", "error"}
_REAPABLE_LIFECYCLE_STATES = {"dead_candidate", "reapable"}


def _fetch_agent_hub_session(session_id: str) -> dict[str, Any] | None:
    headers = build_agent_hub_headers(request_source="sf-pipeline")
    with httpx.Client(timeout=_SESSION_TIMEOUT_SECONDS) as client:
        response = client.get(f"{AGENT_HUB_URL}/api/sessions/{session_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else None


def _session_ready_for_reclaim(session: dict[str, Any] | None) -> bool:
    return session_ready_for_reclaim(
        session,
        final_statuses=_FINAL_SESSION_STATUSES,
        final_health=_FINAL_SESSION_HEALTH,
        reapable_states=_REAPABLE_LIFECYCLE_STATES,
    )


def _close_agent_hub_session(session_id: str) -> bool:
    headers = build_agent_hub_headers(request_source="sf-pipeline")
    with httpx.Client(timeout=_SESSION_TIMEOUT_SECONDS) as client:
        response = client.post(f"{AGENT_HUB_URL}/api/sessions/{session_id}/close", headers=headers)
        response.raise_for_status()
    return True


def _maybe_reclaim_same_task_lane(task_id: str, project_id: str, lane_check: Any) -> tuple[Any, bool]:
    return maybe_reclaim_same_task_lane(
        task_id,
        project_id,
        lane_check,
        fetch_session=_fetch_agent_hub_session,
        session_ready=_session_ready_for_reclaim,
        close_session=_close_agent_hub_session,
        lane_conflicts=check_task_lane_conflicts,
        emit_log=emit_log,
    )


def _guard_existing_same_task_lane(task_id: str, project_id: str) -> dict[str, Any] | None:
    lane_check = check_task_lane_conflicts(task_id, project_id)
    lane_check, reclaimed = _maybe_reclaim_same_task_lane(task_id, project_id, lane_check)
    return same_task_lane_guard_result(
        task_id,
        project_id,
        lane_check,
        reclaimed=reclaimed,
        emit_log=emit_log,
        logger=logger,
    )


def start_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    debug_section("Autonomous Execution", task_id=task_id, project_id=project_id)
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)
    emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)
    duplicate = _guard_existing_same_task_lane(task_id, project_id)
    if duplicate:
        return duplicate
    return execute_task_locked(task_id, project_id, dispatch=dispatch)


def _prepare_execution(task_id: str, project_id: str) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    return prepare_execution(
        task_id,
        project_id,
        task_store=task_store,
        emit_error=emit_error,
        validate_pristine_codebase=validate_pristine_codebase,
        setup_task_checkout=setup_task_checkout,
    )


def _has_active_task_checkpoint(task_id: str, project_id: str) -> bool:
    from cli.lib.checkpoint_metadata import load_snapshot_meta

    return active_task_checkpoint(task_id, project_id, load_snapshot_meta=load_snapshot_meta)


def _prepare_completed_task_closeout(task_id: str, project_id: str) -> dict[str, Any] | None:
    return prepare_completed_task_closeout(
        task_id,
        project_id,
        validate_pristine_codebase=validate_pristine_codebase,
        has_active_task_checkpoint=_has_active_task_checkpoint,
        get_task_checkout=get_task_checkout,
        setup_task_checkout=setup_task_checkout,
        emit_log=emit_log,
    )


def execute_task_locked(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    return execute_task_locked_impl(task_id, project_id, dispatch, deps=_execution_deps())


def _execution_deps() -> dict[str, Any]:
    return {
        "task_store": task_store,
        "emit_error": emit_error,
        "emit_log": emit_log,
        "load_subtasks": _load_subtasks_with_deps,
        "prepare_completed_task_closeout": _prepare_completed_task_closeout,
        "handle_early_completion": handle_early_completion,
        "prepare_execution": _prepare_execution,
        "execute_subtask_loop": execute_subtask_loop,
        "check_main_repo_leakage": check_main_repo_leakage,
        "handle_completion": _handle_completion_with_deps,
        "execute_agent_feedback": execute_agent_feedback,
    }


def _load_subtasks_with_deps(task_id: str, project_id: str) -> tuple[dict[str, Any] | None, list, int, int]:
    return load_subtasks(
        task_id,
        project_id,
        get_subtasks_for_task=get_subtasks_for_task,
        emit_progress=emit_progress,
        emit_error=emit_error,
        task_store=task_store,
    )


def _handle_completion_with_deps(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list,
    incomplete: list,
    dispatch: Callable[[str, str, str], None] | None,
    wind_down_state: Any,
) -> str | None:
    return handle_completion(
        task_id,
        project_id,
        project_path,
        results,
        incomplete,
        dispatch,
        wind_down_state,
        handle_successful_completion=handle_successful_completion,
        handle_partial_completion=handle_partial_completion,
        handle_failed_execution=handle_failed_execution,
    )
