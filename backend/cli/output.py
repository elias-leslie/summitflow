"""JSON output formatters for CLI.

All output functions emit JSON for AI agent consumption.
Default: compact JSON (single-line). Use --human for pretty-printed.
Use --compact for TOON-style one-liner per item.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from .client import APIError

# Module-level flags for output modes
_human_output: bool = False
_compact_output: bool = False
_progress_only: bool = False


def set_human_output(enabled: bool) -> None:
    """Enable or disable human-readable (pretty-printed) output."""
    global _human_output
    _human_output = enabled


def set_compact_output(enabled: bool) -> None:
    """Enable or disable compact TOON-style output."""
    global _compact_output
    _compact_output = enabled


def set_progress_only(enabled: bool) -> None:
    """Enable progress-only mode (single line summary)."""
    global _progress_only
    _progress_only = enabled


def is_compact() -> bool:
    """Check if compact output mode is enabled."""
    return _compact_output


def is_progress_only() -> bool:
    """Check if progress-only mode is enabled."""
    return _progress_only


# --- Compact Formatters ---


def _truncate(s: str, length: int) -> str:
    """Truncate string to length, adding ... if truncated."""
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."


def format_compact_task(task: dict[str, Any]) -> str:
    """Format task as compact one-liner.

    Format: P<priority> <id> <type:7> <status:7> <title:50>
    """
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    task_type = (task.get("task_type") or "task")[:7].ljust(7)
    status = (task.get("status") or "pending")[:7].ljust(7)
    title = _truncate(task.get("title") or "", 50)
    return f"P{priority} {task_id} {task_type} {status} {title}"


def format_compact_subtask(subtask: dict[str, Any]) -> str:
    """Format subtask as compact one-liner.

    Format: <subtask_id> <PASS|____> <description:40> [<done>/<total>]
    """
    subtask_id = subtask.get("subtask_id", "?")
    passes = "PASS" if subtask.get("passes") else "____"
    description = _truncate(subtask.get("description") or "", 40)
    step_summary = subtask.get("step_summary", {})
    done = step_summary.get("completed", 0)
    total = step_summary.get("total", 0)
    return f"{subtask_id:5} {passes} {description:40} [{done}/{total}]"


def format_compact_step(step: dict[str, Any]) -> str:
    """Format step as compact one-liner.

    Format: <step_number> <PASS|____> <description:50>
    """
    step_num = step.get("step_number", 0)
    passes = "PASS" if step.get("passes") else "____"
    description = _truncate(step.get("description") or "", 50)
    return f"{step_num:2} {passes} {description}"


def format_compact_dep(dep: dict[str, Any]) -> str:
    """Format dependency as compact one-liner."""
    from_id = dep.get("from_task_id", "?")
    to_id = dep.get("to_task_id", "?")
    dep_type = (dep.get("dependency_type") or "blocks")[:6].ljust(6)
    return f"{from_id} {dep_type} {to_id}"


def format_compact_capability(cap: dict[str, Any]) -> str:
    """Format capability as compact one-liner."""
    cap_id = (cap.get("id") or "?")[:20].ljust(20)
    test_count = cap.get("test_count", 0)
    status = cap.get("status") or "unknown"
    return f"{cap_id} tests:{test_count} status:{status}"


def format_compact_component(comp: dict[str, Any]) -> str:
    """Format component as compact one-liner."""
    path = (comp.get("path") or "?")[:25].ljust(25)
    file_count = comp.get("file_count", 0)
    return f"{path} files:{file_count}"


def output_json(data: Any) -> None:
    """Output data as JSON to stdout.

    Default: compact single-line JSON for AI consumption.
    With --human flag: pretty-printed with indent=2.
    """
    indent = 2 if _human_output else None
    print(json.dumps(data, default=str, indent=indent))


def output_task(task: dict[str, Any]) -> None:
    """Output a single task."""
    if _compact_output:
        # Single line: id|status|P<priority>|type|done/total subtasks|title
        subtask_summary = task.get("subtask_summary") or {}
        done = subtask_summary.get("completed", 0)
        total = subtask_summary.get("total", 0)
        priority = task.get("priority", 3)
        print(
            f"{task.get('id')}|{task.get('status')}|P{priority}|"
            f"{task.get('task_type')}|{done}/{total} subtasks|{task.get('title')}"
        )
    else:
        output_json(task)


def output_task_list(tasks: list[dict[str, Any]], header: str = "TASKS") -> None:
    """Output a list of tasks."""
    if _compact_output:
        print(f"{header}[{len(tasks)}]")
        for task in tasks:
            print(format_compact_task(task))
    else:
        output_json({"tasks": tasks, "total": len(tasks)})


def output_deps(deps: list[dict[str, Any]]) -> None:
    """Output dependency list."""
    if _compact_output:
        print(f"DEPS[{len(deps)}]")
        for dep in deps:
            print(format_compact_dep(dep))
    else:
        output_json(deps)


def output_capabilities(caps: list[dict[str, Any]]) -> None:
    """Output capabilities."""
    if _compact_output:
        print(f"CAPS[{len(caps)}]")
        for cap in caps:
            print(format_compact_capability(cap))
    else:
        output_json(caps)


def output_components(comps: list[dict[str, Any]]) -> None:
    """Output components."""
    if _compact_output:
        print(f"COMPONENTS[{len(comps)}]")
        for comp in comps:
            print(format_compact_component(comp))
    else:
        output_json(comps)


def output_tests(tests: list[dict[str, Any]]) -> None:
    """Output tests as JSON."""
    output_json(tests)


def output_subtasks(subtasks: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> None:
    """Output subtasks list."""
    if _progress_only:
        # Single line summary only
        if summary:
            done = summary.get("completed", 0)
            total = summary.get("total", 0)
            pct = summary.get("progress_percent", 0)
            print(f"SUBTASKS:{done}/{total}:{pct:.0f}%")
        else:
            print(f"SUBTASKS:{len(subtasks)}")
    elif _compact_output:
        if summary:
            done = summary.get("completed", 0)
            total = summary.get("total", 0)
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
    if _compact_output:
        done = sum(1 for s in steps if s.get("passes"))
        total = len(steps)
        pct = (done / total * 100) if total > 0 else 0
        print(f"STEPS[{total}]:{done}/{total}:{pct:.0f}%")
        for step in steps:
            print(format_compact_step(step))
    else:
        output_json({"steps": steps, "total": len(steps)})


def output_error(message: str) -> None:
    """Output error message to stderr as JSON."""
    print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    """Output success message as JSON."""
    output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    """Output warning message to stderr as JSON."""
    print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit.

    Args:
        e: APIError exception from client
    """
    output_error(e.detail)
    raise typer.Exit(1)
