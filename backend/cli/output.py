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

from . import _output_formatters as fmt
from ._output_formatters import (
    format_compact_dep,
    format_compact_step,
    format_compact_subtask,
    format_compact_task,
    format_context_blockers,
    format_context_decisions,
    format_context_log,
    format_context_references,
    format_context_subtasks,
    format_context_task,
    format_subtask_context_dependencies,
    format_subtask_context_subtask,
    format_subtask_context_task_summary,
)

if TYPE_CHECKING:
    from .client import APIError
    from .config import Config

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


def require_explicit_project(config: Config) -> None:
    """Exit with error if project was resolved from cwd (not explicit flag/env).

    Task creation commands must use -P or ST_PROJECT_ID to avoid
    silent wrong-project association.
    """
    if config.source not in ("cwd",):
        return

    from .config import get_available_projects

    available = get_available_projects()
    available_str = ", ".join(available) if available else "(could not fetch)"
    print(
        f"Error: Task creation requires explicit project.\n"
        f"Usage: st -P <project> create \"title\"\n"
        f"Detected: {config.project_id} (from cwd)\n"
        f"Available: {available_str}",
        file=sys.stderr,
    )
    raise typer.Exit(1)


def output_json(data: Any) -> None:
    """Output data as JSON to stdout."""
    indent = 2 if _human_output else None
    print(json.dumps(data, default=str, indent=indent))


def output_task(task: dict[str, Any]) -> None:
    """Output a single task."""
    if _compact_output:
        subtask_summary = task.get("subtask_summary") or {}
        done = subtask_summary.get("completed", 0)
        total = subtask_summary.get("total", 0)
        priority = task.get("priority", 3)
        complexity = task.get("complexity") or "SIMPLE"
        decisions = task.get("decisions") or []
        decisions_count = len(decisions) if isinstance(decisions, list) else 0
        print(
            f"{task.get('id')}|{task.get('project_id', '')}|{task.get('status')}|P{priority}|"
            f"{task.get('task_type')}|{complexity}|{done}/{total}|"
            f"decisions:{decisions_count}|{task.get('title')}"
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


def output_blocked_tasks(tasks: list[dict[str, Any]], blockers_map: dict[str, list[str]]) -> None:
    """Output blocked tasks with blocker info."""
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
    """Output error message to stderr."""
    if _compact_output:
        print(f"ERROR {message}", file=sys.stderr)
    else:
        print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    """Output success message."""
    if _compact_output:
        print(f"PASS {message}")
    else:
        output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    """Output warning message to stderr."""
    if _compact_output:
        print(f"WARN {message}", file=sys.stderr)
    else:
        print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    detail = e.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        available_agents = detail.get("available_agents", [])
        if available_agents:
            output_error(message)
            print("\nAvailable agents:", file=sys.stderr)
            for agent in available_agents:
                print(f"  {agent}", file=sys.stderr)
            raise typer.Exit(1)
    elif isinstance(detail, list):
        # Pydantic validation errors: extract msg from each error
        messages = [err.get("msg", str(err)) for err in detail if isinstance(err, dict)]
        output_error("; ".join(messages) if messages else str(detail))
        raise typer.Exit(1)
    output_error(detail)
    raise typer.Exit(1)


def output_context(
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> None:
    """Output full task context in TOON format."""
    if _compact_output:
        sections = [
            format_context_task(task),
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
            }
        )


def output_subtask_context(
    task: dict[str, Any],
    subtask: dict[str, Any],
    dependencies: list[dict[str, Any]],
    references: list[dict[str, Any]] | None = None,
) -> None:
    """Output subtask-scoped context in TOON format."""
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
