"""Follow-up task creation for partial completions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ....services.task_execution_readiness import sync_task_execution_readiness
from ....services.task_plan_context import get_plan_subtask_map, normalize_plan_steps
from ....storage import subtasks as subtask_store
from ....storage.connection import get_connection
from ....storage.task_spirit import get_task_spirit, upsert_task_spirit
from ....storage.tasks.columns import TASK_COLUMNS
from ....storage.tasks.core import canonicalize_task_id, create_task, get_task
from ....storage.tasks.mapping import row_to_dict
from ....storage.tasks.update import update_task_fields
from .events import emit_log

_PENDING_STATUS = "pending"


def _normalize_failed_subtask_ids(failed_results: list[dict[str, Any]]) -> list[str]:
    """Return sorted unique usable subtask ids from failed results."""
    normalized: set[str] = set()
    for result in failed_results:
        raw_subtask_id = result.get("subtask_id")
        if not isinstance(raw_subtask_id, str):
            continue
        subtask_id = raw_subtask_id.strip()
        if not subtask_id:
            continue
        normalized.add(subtask_id)
    return sorted(normalized)


def _build_followup_title(task_id: str) -> str:
    """Return exact follow-up title for parent task."""
    return f"Follow-up: stuck subtasks from {task_id}"


def _failure_summary(result: Mapping[str, Any] | None) -> str | None:
    """Return a compact failure summary for task context and description."""
    if not isinstance(result, Mapping):
        return None
    for key in ("error", "message", "summary"):
        value = result.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text[:240]
    return None


def _build_followup_description(task_id: str, failed_results: list[dict[str, Any]]) -> str:
    """Return normalized follow-up description text."""
    lines: list[str] = []
    for subtask_id in _normalize_failed_subtask_ids(failed_results):
        result = next(
            (
                item for item in failed_results
                if str(item.get("subtask_id") or "").strip() == subtask_id
            ),
            None,
        )
        summary = _failure_summary(result)
        if summary:
            lines.append(f"- {subtask_id}: {summary}")
        else:
            lines.append(f"- {subtask_id}")
    failed_desc = "\n".join(lines) if lines else "- __no_subtask_ids__"
    return (
        f"Partial merge completed for task {task_id}. "
        f"The following subtasks could not be resolved:\n\n"
        f"{failed_desc}\n\n"
        f"These need to be re-attempted with a fresh approach."
    )


def _resolve_parent_task_id(task_id: str | None) -> str | None:
    """Return canonical parent task id when input is usable and exists."""
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    parent_task_id = canonicalize_task_id(task_id)
    if get_task(parent_task_id) is None:
        return None
    return parent_task_id


def _find_pending_followup_task(
    parent_task_id: str,
    project_id: str,
    title: str,
) -> dict[str, Any] | None:
    """Return oldest pending direct child follow-up task."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE project_id = %s
              AND parent_task_id = %s
              AND title = %s
              AND status = %s
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (project_id, parent_task_id, title, _PENDING_STATUS),
        )
        row = cur.fetchone()
    return row_to_dict(row) if row else None


def _display_order(subtask: Mapping[str, Any], fallback: int) -> int:
    raw = subtask.get("display_order")
    if raw is None:
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _list_of_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [text for value in values if (text := str(value or "").strip())]


def _copy_steps(steps: Any) -> list[dict[str, Any]]:
    return [dict(step) for step in normalize_plan_steps(steps)]


def _merge_labels(parent_task: Mapping[str, Any] | None) -> list[str]:
    labels = _list_of_strings((parent_task or {}).get("labels"))
    if "autocode-followup" not in labels:
        labels.append("autocode-followup")
    return labels


def _build_done_when(
    parent_task_id: str,
    followup_subtasks: list[dict[str, Any]],
) -> list[str]:
    criteria = [f"Resolve unresolved work carried from {parent_task_id}"]
    criteria.extend(
        f"{subtask['subtask_id']} {subtask['description']}"
        for subtask in followup_subtasks
        if subtask.get("subtask_id") and subtask.get("description")
    )
    criteria.append("Focused validation passes for the follow-up changes")
    return criteria


def _build_followup_subtasks(
    parent_task_id: str,
    parent_spirit: Mapping[str, Any] | None,
    failed_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failed_ids = _normalize_failed_subtask_ids(failed_results)
    failed_set = set(failed_ids)
    result_map = {
        str(result.get("subtask_id") or "").strip(): result
        for result in failed_results
        if str(result.get("subtask_id") or "").strip()
    }
    parent_subtasks = subtask_store.get_subtasks_for_task(parent_task_id, include_steps=True)
    subtask_map = {
        str(subtask.get("subtask_id") or "").strip(): subtask
        for subtask in parent_subtasks
        if str(subtask.get("subtask_id") or "").strip()
    }
    plan_subtask_map = get_plan_subtask_map((parent_spirit or {}).get("context"))

    package: list[dict[str, Any]] = []
    for fallback_order, subtask_id in enumerate(failed_ids, start=1):
        source = subtask_map.get(subtask_id) or plan_subtask_map.get(subtask_id) or {}
        description = str(source.get("description") or "").strip() or f"Retry failed subtask {subtask_id}"
        package.append(
            {
                "subtask_id": subtask_id,
                "description": description,
                "display_order": _display_order(source, fallback_order),
                "phase": str(source.get("phase") or "").strip() or None,
                "subtask_type": str(source.get("subtask_type") or "").strip() or None,
                "depends_on": [
                    dep for dep in _list_of_strings(source.get("depends_on"))
                    if dep in failed_set
                ],
                "steps": _copy_steps(source.get("steps")),
                "failure_summary": _failure_summary(result_map.get(subtask_id)),
            }
        )

    package.sort(key=lambda subtask: (_display_order(subtask, 0), str(subtask.get("subtask_id") or "")))
    return package


def _build_followup_context(
    parent_task_id: str,
    parent_task: Mapping[str, Any] | None,
    parent_spirit: Mapping[str, Any] | None,
    followup_subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    parent_context = (parent_spirit or {}).get("context")
    context = dict(parent_context) if isinstance(parent_context, Mapping) else {}
    context["source_task_id"] = parent_task_id
    context["followup_reason"] = "partial_completion"
    context["failed_subtask_ids"] = [subtask["subtask_id"] for subtask in followup_subtasks]
    if "objective" not in context:
        title = str((parent_task or {}).get("title") or parent_task_id).strip()
        context["objective"] = f"Finish unresolved work from {title}"
    parent_done_when = _list_of_strings((parent_spirit or {}).get("done_when"))
    if parent_done_when:
        context["parent_done_when"] = parent_done_when
    failure_summaries = {
        subtask["subtask_id"]: subtask["failure_summary"]
        for subtask in followup_subtasks
        if subtask.get("failure_summary")
    }
    if failure_summaries:
        context["failure_summaries"] = failure_summaries
    context["subtasks"] = [
        {
            key: value
            for key, value in {
                "subtask_id": subtask.get("subtask_id"),
                "description": subtask.get("description"),
                "phase": subtask.get("phase"),
                "subtask_type": subtask.get("subtask_type"),
                "depends_on": subtask.get("depends_on"),
                "steps": subtask.get("steps"),
            }.items()
            if value not in (None, "", [], {})
        }
        for subtask in followup_subtasks
    ]
    return context


def _sync_followup_package(
    followup_task_id: str,
    parent_task_id: str,
    project_id: str,
    failed_results: list[dict[str, Any]],
) -> None:
    parent_task = get_task(parent_task_id) or {}
    parent_spirit = get_task_spirit(parent_task_id) or {}
    followup_subtasks = _build_followup_subtasks(parent_task_id, parent_spirit, failed_results)
    done_when = _build_done_when(parent_task_id, followup_subtasks)
    context = _build_followup_context(parent_task_id, parent_task, parent_spirit, followup_subtasks)

    with get_connection() as conn, conn.transaction():
        subtask_store.delete_subtasks_for_task(followup_task_id)
        for display_order, subtask in enumerate(followup_subtasks):
            subtask_store.create_subtask(
                followup_task_id,
                str(subtask["subtask_id"]),
                str(subtask["description"]),
                display_order,
                phase=subtask.get("phase"),
                steps=subtask.get("steps"),
                depends_on=subtask.get("depends_on"),
                subtask_type=subtask.get("subtask_type"),
            )

        dependencies = [
            (str(subtask["subtask_id"]), dependency)
            for subtask in followup_subtasks
            for dependency in _list_of_strings(subtask.get("depends_on"))
        ]
        if dependencies:
            subtask_store.bulk_add_subtask_dependencies(followup_task_id, dependencies)

        upsert_task_spirit(
            task_id=followup_task_id,
            done_when=done_when,
            context=context,
            complexity=str(
                (parent_spirit or {}).get("complexity")
                or (parent_task or {}).get("complexity")
                or "STANDARD"
            ),
        )
    readiness = sync_task_execution_readiness(
        followup_task_id,
        approved_by="autocode-followup",
    )
    emit_log(
        parent_task_id,
        "info",
        f"Follow-up task {followup_task_id} packaged as execution-ready={readiness.ready}",
        project_id=project_id,
    )


def _reuse_followup(
    parent_task_id: str,
    project_id: str,
    followup_task: dict[str, Any],
    description: str,
    failed_results: list[dict[str, Any]],
) -> str:
    update_task_fields(followup_task["id"], description=description)
    _sync_followup_package(followup_task["id"], parent_task_id, project_id, failed_results)
    emit_log(
        parent_task_id,
        "info",
        f"Reused follow-up task {followup_task['id']} for failed subtasks",
        project_id=project_id,
    )
    return str(followup_task["id"])


def create_followup_task_for_failures(
    task_id: str | None,
    project_id: str,
    failed_results: list[dict[str, Any]],
) -> str | None:
    """Create or reuse a follow-up task for failed subtasks."""
    parent_task_id = _resolve_parent_task_id(task_id)
    if parent_task_id is None:
        emit_log(
            task_id if isinstance(task_id, str) else "",
            "warn",
            "Skipped follow-up task creation: invalid parent task id",
            project_id=project_id,
        )
        return None

    try:
        title = _build_followup_title(parent_task_id)
        description = _build_followup_description(parent_task_id, failed_results)
        existing_followup = _find_pending_followup_task(parent_task_id, project_id, title)
        if existing_followup is not None:
            return _reuse_followup(
                parent_task_id,
                project_id,
                existing_followup,
                description,
                failed_results,
            )

        parent_task = get_task(parent_task_id) or {}
        created_followup = create_task(
            project_id=project_id,
            title=title,
            description=description,
            task_type=parent_task.get("task_type") or "task",
            priority=1,
            parent_task_id=parent_task_id,
            autonomous=True,
        )
        update_task_fields(
            created_followup["id"],
            labels=_merge_labels(parent_task),
        )
        authoritative_followup = _find_pending_followup_task(parent_task_id, project_id, title)
        if authoritative_followup is not None:
            if authoritative_followup["id"] == created_followup["id"]:
                _sync_followup_package(created_followup["id"], parent_task_id, project_id, failed_results)
                emit_log(
                    parent_task_id,
                    "info",
                    f"Created follow-up task {created_followup['id']} for failed subtasks",
                    project_id=project_id,
                )
                return str(created_followup["id"])
            return _reuse_followup(
                parent_task_id,
                project_id,
                authoritative_followup,
                description,
                failed_results,
            )

        follow_up_id = str(created_followup.get("id", "unknown"))
        _sync_followup_package(follow_up_id, parent_task_id, project_id, failed_results)
        emit_log(
            parent_task_id,
            "info",
            f"Created follow-up task {follow_up_id} for failed subtasks",
            project_id=project_id,
        )
        return follow_up_id
    except Exception as e:
        emit_log(
            parent_task_id,
            "warn",
            f"Failed to create follow-up task: {e}",
            project_id=project_id,
        )
        return None
