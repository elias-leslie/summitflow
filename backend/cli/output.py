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


def output_json(data: Any) -> None:
    """Output data as JSON to stdout.

    Default: compact single-line JSON for AI consumption.
    With --human flag: pretty-printed with indent=2.
    """
    indent = 2 if _human_output else None
    print(json.dumps(data, default=str, indent=indent))


def output_task(task: dict[str, Any]) -> None:
    """Output a single task.

    Compact format includes fields needed for /do_it pre-checks:
    id|status|P<priority>|type|complexity|done/total|criteria:N|title
    """
    if _compact_output:
        subtask_summary = task.get("subtask_summary") or {}
        done = subtask_summary.get("completed", 0)
        total = subtask_summary.get("total", 0)
        priority = task.get("priority", 3)
        complexity = task.get("complexity") or "SIMPLE"
        # criteria_count comes from task_criteria join (populated by API)
        criteria_count = task.get("criteria_count", 0)
        decisions = task.get("decisions") or []
        decisions_count = len(decisions) if isinstance(decisions, list) else 0
        print(
            f"{task.get('id')}|{task.get('status')}|P{priority}|"
            f"{task.get('task_type')}|{complexity}|{done}/{total}|"
            f"criteria:{criteria_count}|decisions:{decisions_count}|{task.get('title')}"
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
    """Output blocked tasks with blocker info.

    Compact format:
    BLOCKED[N]
    P<priority> <task-id> <type> <status> <title>
      ↳ blocked by: <blocker-id>|<blocker-status>|<blocker-title>
    """
    if _compact_output:
        print(f"BLOCKED[{len(tasks)}]")
        for task in tasks:
            # Print task line
            print(format_compact_task(task))
            # Print blockers indented
            blockers = task.get("blockers", [])
            for b in blockers:
                blocker_id = b.get("depends_on_task_id", "?")
                blocker_status = b.get("depends_on_status", "?")
                blocker_title = _truncate(b.get("depends_on_title", ""), 40)
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
    """Output error message to stderr.

    In compact mode: ERROR <message>
    Otherwise: JSON {"error": "..."}
    """
    if _compact_output:
        print(f"ERROR {message}", file=sys.stderr)
    else:
        print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    """Output success message.

    In compact mode: PASS <message>
    Otherwise: JSON {"success": true, "message": "..."}
    """
    if _compact_output:
        print(f"PASS {message}")
    else:
        output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    """Output warning message to stderr.

    In compact mode: WARN <message>
    Otherwise: JSON {"warning": "..."}
    """
    if _compact_output:
        print(f"WARN {message}", file=sys.stderr)
    else:
        print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit.

    Args:
        e: APIError exception from client
    """
    output_error(e.detail)
    raise typer.Exit(1)


# --- Context Output Formatters ---


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output.

    Format: TASK:<id>|<status>|P<priority>|<type>|<complexity>
    OBJECTIVE:<objective>
    SPIRIT_ANTI:<anti-patterns>
    CONSTRAINTS[N]:<constraint1>|<constraint2>|...
    DONE_WHEN[N]:<criterion1>|<criterion2>|...
    """
    lines = []
    task_id = task.get("id", "unknown")
    status = task.get("status", "pending")
    priority = task.get("priority", 3)
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"

    lines.append(f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}")

    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{_truncate(objective, 100)}")

    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{_truncate(spirit_anti, 150)}")

    constraints = task.get("constraints") or []
    if constraints:
        lines.append(f"CONSTRAINTS[{len(constraints)}]:{' | '.join(constraints)}")

    done_when = task.get("done_when") or []
    if done_when:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")

    return "\n".join(lines)


def format_context_decisions(decisions: list[dict[str, Any]]) -> str:
    """Format decisions for context output.

    Format: DECISIONS[N]
    d<id>:<title>→<outcome>
    """
    if not decisions:
        return ""

    lines = [f"DECISIONS[{len(decisions)}]"]
    for d in decisions:
        d_id = d.get("id", "?")
        title = d.get("title", "")
        outcome = d.get("outcome", "")
        lines.append(f"{d_id}:{_truncate(title, 30)}→{_truncate(outcome, 80)}")

    return "\n".join(lines)


def format_context_subtasks(subtasks: list[dict[str, Any]]) -> str:
    """Format subtasks with steps inline for context output.

    Format: SUBTASKS[N]:<done>/<total>:<pct>%
    <subtask_id> <PASS|____> <description> [steps: <done>/<total>]
      1. <PASS|____> <step_desc>
      2. <PASS|____> <step_desc>
    """
    if not subtasks:
        return "SUBTASKS[0]:0/0:0%"

    done = sum(1 for s in subtasks if s.get("passes"))
    total = len(subtasks)
    pct = (done / total * 100) if total > 0 else 0

    lines = [f"SUBTASKS[{total}]:{done}/{total}:{pct:.0f}%"]

    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id", "?")
        passes = "PASS" if subtask.get("passes") else "____"
        desc = _truncate(subtask.get("description") or "", 50)
        step_summary = subtask.get("step_summary", {})
        step_done = step_summary.get("completed", 0)
        step_total = step_summary.get("total", 0)

        lines.append(f"{subtask_id:5} {passes} {desc} [{step_done}/{step_total}]")

        # Include steps inline
        steps = subtask.get("steps") or []
        for step in steps:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            step_desc = _truncate(step.get("description") or "", 60)
            lines.append(f"  {step_num}. {step_pass} {step_desc}")

    return "\n".join(lines)


def format_context_criteria(criteria: list[dict[str, Any]]) -> str:
    """Format acceptance criteria for context output.

    Format: CRITERIA[N]:<verified>/<total>
    <criterion_id> <PASS|____> <criterion>
      verify_by:<test|agent|human> cmd:<verify_command> expect:<expected_output>
    """
    if not criteria:
        return "CRITERIA[0]:0/0"

    verified = sum(1 for c in criteria if c.get("verified"))
    total = len(criteria)

    lines = [f"CRITERIA[{total}]:{verified}/{total}"]

    for c in criteria:
        c_id = c.get("criterion_id", "?")
        passes = "PASS" if c.get("verified") else "____"
        criterion = _truncate(c.get("criterion") or "", 60)
        lines.append(f"{c_id} {passes} {criterion}")

        verify_by = c.get("verify_by") or "human"
        verify_cmd = c.get("verify_command") or ""
        expected = c.get("expected_output") or ""

        if verify_cmd or expected:
            cmd_str = _truncate(verify_cmd, 50) if verify_cmd else "-"
            expect_str = _truncate(expected, 30) if expected else "-"
            lines.append(f"  verify_by:{verify_by} cmd:{cmd_str} expect:{expect_str}")

    return "\n".join(lines)


def format_context_blockers(blockers: list[dict[str, Any]]) -> str:
    """Format blockers for context output.

    Format: BLOCKERS[N]
    <blocker_task_id>|<status>|<title>
    """
    if not blockers:
        return ""

    lines = [f"BLOCKERS[{len(blockers)}]"]
    for b in blockers:
        b_id = b.get("id", "?")
        status = b.get("status", "?")
        title = _truncate(b.get("title") or "", 50)
        lines.append(f"{b_id}|{status}|{title}")

    return "\n".join(lines)


def output_context(
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    blockers: list[dict[str, Any]] | None = None,
) -> None:
    """Output full task context in TOON format.

    Combines task header, decisions, subtasks with steps, criteria, and blockers.
    """
    if _compact_output:
        sections = [
            format_context_task(task),
            format_context_decisions(task.get("decisions") or []),
            format_context_subtasks(subtasks),
            format_context_criteria(criteria),
        ]

        if blockers:
            sections.append(format_context_blockers(blockers))

        print("\n".join(s for s in sections if s))
    else:
        output_json(
            {
                "task": task,
                "subtasks": subtasks,
                "criteria": criteria,
                "blockers": blockers or [],
            }
        )
