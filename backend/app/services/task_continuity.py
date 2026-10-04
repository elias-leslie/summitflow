"""Shared helpers for bounded task continuity output."""

from __future__ import annotations

import hashlib
from typing import Any

# Active continuity keeps three progress entries, each at most this many UTF-8
# bytes including its omission marker. Exact task logs and exports stay intact.
# Retained task-log entries on 2026-10-03: p99=1535 bytes; this cap preserves
# 3730/3767 entries (99.02%) while bounding the observed 11059-byte maximum.
MAX_PROGRESS_ENTRY_BYTES = 1536


def _task_context(task: dict[str, Any], spirit: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(task.get("context"), dict):
        return task["context"]
    if isinstance((spirit or {}).get("context"), dict):
        return (spirit or {})["context"]
    return {}


def _objective(task: dict[str, Any], spirit: dict[str, Any] | None) -> str:
    context = _task_context(task, spirit)
    text = str(
        (spirit or {}).get("objective")
        or task.get("objective")
        or context.get("objective")
        or ""
    ).strip()
    return text or "none recorded"


def _sorted_incomplete_subtasks(subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    incomplete = [subtask for subtask in subtasks if not subtask.get("passes")]
    return sorted(
        incomplete,
        key=lambda subtask: (
            int(subtask.get("display_order", 0) or 0),
            str(subtask.get("subtask_id") or ""),
        ),
    )


def _pick_current_slice(
    subtasks: list[dict[str, Any]],
    summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    summary = summary or {}
    next_subtask_id = str(summary.get("next_subtask_id") or "").strip()
    if next_subtask_id:
        for subtask in subtasks:
            if subtask.get("subtask_id") == next_subtask_id and not subtask.get("passes"):
                return subtask
    incomplete = _sorted_incomplete_subtasks(subtasks)
    return incomplete[0] if incomplete else None


def _current_slice_text(subtask: dict[str, Any] | None) -> str:
    if not subtask:
        return "none inferred"
    return f"{subtask.get('subtask_id')} {subtask.get('description') or ''}".strip()


def _normalize_step(step: Any, index: int) -> tuple[int, str, bool]:
    if isinstance(step, dict):
        step_number = int(step.get("step_number") or index)
        description = str(step.get("description") or "").strip()
        return step_number, description, bool(step.get("passes"))
    return index, str(step).strip(), False


def _next_action(subtask: dict[str, Any] | None) -> str:
    if not subtask:
        return "none inferred"
    steps = subtask.get("steps") or subtask.get("steps_from_table") or []
    for index, step in enumerate(steps, start=1):
        step_number, description, passes = _normalize_step(step, index)
        if description and not passes:
            return f"{subtask.get('subtask_id')}.{step_number} {description}".strip()
    return _current_slice_text(subtask)


def _progress_excerpt(entry: str, task_id: str) -> str:
    """Bound the projection, retaining the timestamp and latest trailing decision.

    The digest identifies the exact timestamped entry returned by task logs/export,
    before display whitespace normalization. Source identity is task ID + digest;
    callers do not provide the underlying storage event ID.
    """
    text = entry.strip()
    original = entry.encode("utf-8")
    encoded = text.encode("utf-8")
    if len(original) <= MAX_PROGRESS_ENTRY_BYTES:
        return text

    digest = hashlib.sha256(original).hexdigest()

    def marker(omitted: int) -> str:
        return (
            f"\n[omitted {omitted} bytes; source={task_id}; sha256={digest}; "
            f"bytes={len(original)}; detail=st export {task_id}]\n"
        )

    # Reserving the largest omitted count guarantees the final marker fits too.
    budget = MAX_PROGRESS_ENTRY_BYTES - len(marker(len(original)).encode("utf-8"))
    if len(encoded) <= budget:
        head, tail = text, ""
    else:
        head_budget = max(budget, 0) * 3 // 4
        tail_budget = max(budget, 0) - head_budget
        head = encoded[:head_budget].decode("utf-8", errors="ignore")
        tail = encoded[-tail_budget:].decode("utf-8", errors="ignore") if tail_budget else ""
    retained_bytes = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
    return f"{head}{marker(len(original) - retained_bytes)}{tail}"


def _recent_progress(progress_log: list[str] | None, task_id: str) -> list[str]:
    cleaned: list[str] = []
    previous: str | None = None
    for entry in progress_log or []:
        text = str(entry).strip()
        if not text:
            continue
        if previous == text:
            continue
        cleaned.append(str(entry))
        previous = text
    return [_progress_excerpt(entry, task_id) for entry in cleaned[-3:]]


def _dependency_blockers(
    current_slice: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> list[str]:
    if not current_slice:
        return []
    statuses = {
        str(subtask.get("subtask_id") or ""): bool(subtask.get("passes"))
        for subtask in subtasks
    }
    blockers: list[str] = []
    for dependency in current_slice.get("depends_on") or []:
        dep_id = str(dependency).strip()
        if not dep_id:
            continue
        if statuses.get(dep_id) is False:
            blockers.append(f"{dep_id} incomplete dependency")
    return blockers


def _external_blockers(blockers: list[dict[str, Any]]) -> list[str]:
    return [
        f"{blocker.get('id')}|{blocker.get('status')}|{blocker.get('title') or ''}"
        for blocker in sorted(blockers, key=lambda blocker: str(blocker.get("id") or ""))
    ]


def _cap_with_note(items: list[str], cap: int) -> list[str]:
    if len(items) <= cap:
        return items
    remainder = len(items) - cap
    return [*items[:cap], f"+{remainder} more omitted"]


def _key_files(task: dict[str, Any], spirit: dict[str, Any] | None) -> list[str]:
    context = _task_context(task, spirit)
    ordered: list[str] = []
    seen: set[str] = set()
    for group in (context.get("files_to_modify") or [], context.get("files_to_create") or []):
        for path in group:
            text = str(path).strip()
            if not text or text in seen:
                continue
            ordered.append(text)
            seen.add(text)
    return _cap_with_note(ordered, 8)


def build_continuity(
    *,
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    progress_log: list[str] | None,
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build additive continuity contract for task context surfaces."""
    current_slice = _pick_current_slice(subtasks, summary)
    continuity_blockers = _cap_with_note(
        _external_blockers(blockers) + _dependency_blockers(current_slice, subtasks),
        3,
    )
    return {
        "objective": _objective(task, spirit),
        "current_slice": _current_slice_text(current_slice),
        "blockers": continuity_blockers,
        "recent_progress": _recent_progress(progress_log, str(task.get("id") or "")),
        "next_action": _next_action(current_slice),
        "key_files": _key_files(task, spirit),
    }


def format_continuity_lines(continuity: dict[str, Any] | None) -> list[str]:
    """Render continuity object into ordered TOON lines."""
    continuity = continuity or {}
    blockers = continuity.get("blockers") or []
    recent_progress = continuity.get("recent_progress") or []
    key_files = continuity.get("key_files") or []

    lines = [
        f"OBJECTIVE:{continuity.get('objective') or 'none recorded'}",
        f"CURRENT_SLICE:{continuity.get('current_slice') or 'none inferred'}",
    ]
    if blockers:
        lines.append(f"BLOCKERS[{len(blockers)}]")
        lines.extend(f"  {item}" for item in blockers)
    else:
        lines.append("BLOCKERS:none explicit")
    if recent_progress:
        lines.append(f"RECENT_PROGRESS[{len(recent_progress)}]")
        lines.extend(f"  {item}" for item in recent_progress)
    else:
        lines.append("RECENT_PROGRESS:none recorded")
    lines.append(f"NEXT_ACTION:{continuity.get('next_action') or 'none inferred'}")
    if key_files:
        lines.append(f"KEY_FILES[{len(key_files)}]:{','.join(str(item) for item in key_files)}")
    else:
        lines.append("KEY_FILES:none recorded")
    return lines
