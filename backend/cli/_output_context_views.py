"""Output functions for task and subtask context views."""

from __future__ import annotations

from typing import Any

from ._output_core import output_json
from ._output_formatters import (
    format_context_blockers,
    format_context_decisions,
    format_context_log,
    format_context_references,
    format_context_snapshot,
    format_context_subtasks,
    format_context_task,
    format_subtask_context_dependencies,
    format_subtask_context_subtask,
    format_subtask_context_task_summary,
)


def output_context(
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> None:
    """Output full task context in TOON format."""
    from ._output_state import _compact_output

    if _compact_output:
        sections = [
            format_context_task(task),
            format_context_snapshot(snapshot or {}),
            format_context_decisions(task.get("decisions") or []),
            format_context_subtasks(subtasks),
        ]
        if blockers:
            sections.append(format_context_blockers(blockers))
        if references:
            sections.append(format_context_references(references))
        if task.get("progress_log"):
            sections.append(format_context_log(task["progress_log"]))
        print("\n".join(s for s in sections if s))
    else:
        output_json(
            {
                "task": task,
                "subtasks": subtasks,
                "blockers": blockers or [],
                "references": references or [],
                "snapshot": snapshot,
            }
        )


def output_subtask_context(
    task: dict[str, Any],
    subtask: dict[str, Any],
    dependencies: list[dict[str, Any]],
    references: list[dict[str, Any]] | None = None,
) -> None:
    """Output subtask-scoped context in TOON format."""
    from ._output_state import _compact_output

    if _compact_output:
        sections = [
            format_subtask_context_task_summary(task),
            format_subtask_context_subtask(subtask),
        ]
        if dependencies:
            sections.append(format_subtask_context_dependencies(dependencies))
        if references:
            sections.append(format_context_references(references, header="PHASE_REFS"))
        print("\n".join(s for s in sections if s))
    else:
        output_json(
            {
                "task_summary": {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "objective": task.get("objective"),
                    "spirit_anti": task.get("spirit_anti"),
                    "done_when": task.get("done_when"),
                },
                "subtask": subtask,
                "dependencies": dependencies,
                "references": references or [],
            }
        )
