"""Quality-result upkeep task generation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.logging_config import get_logger
from app.storage import quality_check_results as qcr_store
from app.storage.connection import get_connection

from .upkeep_constants import QUALITY_DEFAULTS, SOURCE_QUALITY, TASK_TYPE_BUG
from .upkeep_models import CreatedSignalTask, SignalTaskSpec
from .upkeep_signals import create_signal_task, source_key, task_exists_for_upkeep_source

logger = get_logger(__name__)


def normalize_quality_key_part(value: object, default: str) -> str:
    from .upkeep_constants import EMPTY_KEY_PARTS

    text = str(value or "").strip()
    return default if not text or text in EMPTY_KEY_PARTS else text


def quality_source_key(result: dict[str, Any]) -> str | None:
    """Build stable source key for actionable quality failures."""
    parts = {
        key: normalize_quality_key_part(result.get(key), default)
        for key, default in QUALITY_DEFAULTS.items()
    }
    if parts["file_path"] != QUALITY_DEFAULTS["file_path"]:
        stable_id = f"{parts['check_type']}:{parts['check_name']}:{parts['file_path']}:{parts['line_number']}"
        return source_key(SOURCE_QUALITY, stable_id)
    error_message = str(result.get("error_message") or "").strip()
    if not error_message:
        return None
    digest = hashlib.sha1(error_message[:2000].encode()).hexdigest()[:12]
    stable_id = f"{parts['check_type']}:{parts['check_name']}:project:{digest}"
    return source_key(SOURCE_QUALITY, stable_id)


def files_to_modify_from_result(result: dict[str, Any]) -> list[str]:
    file_path = result.get("file_path")
    return [str(file_path)] if isinstance(file_path, str) and file_path else []


def list_unfixed_quality_results(project_id: str, limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return qcr_store.list_check_results(
            conn,
            project_id,
            status="fail",
            unfixed_only=True,
            limit=limit,
        )


def mark_quality_escalated(result_id: int, task_id: str) -> None:
    with get_connection() as conn:
        qcr_store.mark_escalated(conn, result_id, task_id)
        conn.commit()


def quality_task_spec(result: dict[str, Any], result_id: int, source_key_value: str) -> SignalTaskSpec:
    check_type = str(result.get("check_type") or QUALITY_DEFAULTS["check_type"])
    check_name = str(result.get("check_name") or "failure")
    file_path = str(result.get("file_path") or QUALITY_DEFAULTS["file_path"])
    line_number = result.get("line_number")
    location = f"{file_path}:{line_number}" if line_number else file_path
    parts = [
        "Routine upkeep found an unfixed quality failure.",
        "",
        f"Check type: {result.get('check_type') or QUALITY_DEFAULTS['check_type']}",
        f"Check name: {result.get('check_name') or QUALITY_DEFAULTS['check_name']}",
        f"File: {result.get('file_path') or QUALITY_DEFAULTS['check_name']}",
        f"Quality result ID: {result_id}",
    ]
    if line_number:
        parts.append(f"Line: {line_number}")
    if result.get("error_message"):
        parts.extend(["", "Error:", "```", str(result["error_message"])[:1200], "```"])
    return SignalTaskSpec(
        source_key=source_key_value,
        signal_type=SOURCE_QUALITY,
        title=f"Fix: {check_type} {check_name} in {location}",
        description="\n".join(parts),
        priority=2,
        task_type=TASK_TYPE_BUG,
        files_to_modify=files_to_modify_from_result(result),
        subtask_description=f"Resolve quality failure {result_id}",
        source_context={"quality_result_id": result_id},
    )


def coerce_result_id(result_id: object) -> int | None:
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


def quality_task_from_result(project_id: str, result: dict[str, Any]) -> CreatedSignalTask | None:
    result_id = coerce_result_id(result.get("id"))
    if result_id is None or result.get("escalation_task_id"):
        return None
    source_key_value = quality_source_key(result)
    if source_key_value is None:
        logger.info("routine_upkeep_skipping_unactionable_quality_result", result_id=result_id)
        return None
    if task_exists_for_upkeep_source(project_id, source_key_value):
        return None
    task_id = create_signal_task(project_id, quality_task_spec(result, result_id, source_key_value))
    mark_quality_escalated(result_id, task_id)
    return CreatedSignalTask(task_id=task_id, source_key=source_key_value)


def create_quality_failure_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous bug tasks for unfixed quality failures."""
    created: list[str] = []
    for result in list_unfixed_quality_results(project_id, limit):
        created_task = quality_task_from_result(project_id, result)
        if created_task is None:
            continue
        created.append(created_task.task_id)
        if len(created) >= limit:
            break
    return created
