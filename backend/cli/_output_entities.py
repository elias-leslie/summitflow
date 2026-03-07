"""Output functions for tasks, subtasks, steps, deps, and tests."""

from __future__ import annotations

from typing import Any

from . import _output_formatters as fmt
from ._output_core import output_json
from ._output_formatters import (
    format_compact_dep,
    format_compact_step,
    format_compact_subtask,
    format_compact_task,
)


def output_task(task: dict[str, Any]) -> None:
    """Output a single task."""
    from ._output_state import _compact_output

    if _compact_output:
        subtask_summary = task.get("subtask_summary") or {}
        done = subtask_summary.get("completed", 0)
        total = subtask_summary.get("total", 0)
        priority = task.get("priority", 3)
        complexity = task.get("complexity") or "SIMPLE"
        execution_mode = task.get("execution_mode") or "manual"
        decisions = task.get("decisions") or []
        decisions_count = len(decisions) if isinstance(decisions, list) else 0
        print(
            f"{task.get('id')}|{task.get('project_id', '')}|{task.get('status')}|P{priority}|"
            f"{task.get('task_type')}|{complexity}|{done}/{total}|"
            f"{execution_mode}|decisions:{decisions_count}|{task.get('title')}"
        )
    else:
        output_json(task)


def output_task_list(tasks: list[dict[str, Any]], header: str = "TASKS") -> None:
    """Output a list of tasks."""
    from ._output_state import _compact_output

    if _compact_output:
        print(f"{header}[{len(tasks)}]")
        for task in tasks:
            print(format_compact_task(task))
    else:
        output_json({"tasks": tasks, "total": len(tasks)})


def output_blocked_tasks(tasks: list[dict[str, Any]], blockers_map: dict[str, list[str]]) -> None:
    """Output blocked tasks with blocker info."""
    from ._output_state import _compact_output

    if _compact_output:
        print(f"BLOCKED[{len(tasks)}]")
        for task in tasks:
            print(format_compact_task(task))
            blockers = task.get("blockers", [])
            for b in blockers:
                blocker_id = b.get("depends_on_task_id", "?")
                blocker_status = b.get("depends_on_status", "?")
                blocker_title = fmt.truncate(b.get("depends_on_title", ""), 40)
                print(f"  ↳ blocked by: {blocker_id}|{blocker_status}|{blocker_title}")
    else:
        output_json({"tasks": tasks, "blockers_impact": blockers_map})


def output_deps(deps: list[dict[str, Any]]) -> None:
    """Output dependency list."""
    from ._output_state import _compact_output

    if _compact_output:
        print(f"DEPS[{len(deps)}]")
        for dep in deps:
            print(format_compact_dep(dep))
    else:
        output_json(deps)


def output_tests(tests: list[dict[str, Any]]) -> None:
    """Output tests as JSON."""
    output_json(tests)


def output_subtasks(subtasks: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> None:
    """Output subtasks list."""
    from ._output_state import _compact_output, _progress_only

    if _progress_only:
        if summary:
            done, total = summary.get("completed", 0), summary.get("total", 0)
            pct = summary.get("progress_percent", 0)
            print(f"SUBTASKS:{done}/{total}:{pct:.0f}%")
        else:
            print(f"SUBTASKS:{len(subtasks)}")
    elif _compact_output:
        if summary:
            done, total = summary.get("completed", 0), summary.get("total", 0)
            pct = summary.get("progress_percent", 0)
            print(f"SUBTASKS[{total}]:{done}/{total}:{pct:.0f}%")
        else:
            print(f"SUBTASKS[{len(subtasks)}]")
        for subtask in subtasks:
            print(format_compact_subtask(subtask))
    else:
        output_json({"subtasks": subtasks, "summary": summary})


def output_steps(steps: list[dict[str, Any]], subtask_id: str = "") -> None:
    """Output steps list."""
    from ._output_state import _compact_output

    if _compact_output:
        done = sum(1 for s in steps if s.get("passes"))
        total = len(steps)
        pct = (done / total * 100) if total > 0 else 0
        print(f"STEPS[{total}]:{done}/{total}:{pct:.0f}%")
        for step in steps:
            print(format_compact_step(step))
    else:
        output_json({"steps": steps, "total": len(steps)})
