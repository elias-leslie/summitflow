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

    Format: P<priority> <id> <type:10> <status:7> <title:50>
    Types: feature, bug, task, refactor, debt, regression
    """
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    task_type = (task.get("task_type") or "task")[:10].ljust(10)
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

    Compact format: id|status|P<priority>|type|complexity|done/total|decisions:N|title
    """
    if _compact_output:
        subtask_summary = task.get("subtask_summary") or {}
        done = subtask_summary.get("completed", 0)
        total = subtask_summary.get("total", 0)
        priority = task.get("priority", 3)
        complexity = task.get("complexity") or "SIMPLE"
        decisions = task.get("decisions") or []
        decisions_count = len(decisions) if isinstance(decisions, list) else 0
        print(
            f"{task.get('id')}|{task.get('status')}|P{priority}|"
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

    Special handling for agent_slug errors to display available agents.
    """
    detail = e.detail

    # Check if detail is a dict with available_agents (from agent_slug validation)
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        available_agents = detail.get("available_agents", [])

        if available_agents:
            output_error(message)
            print("\nAvailable agents:", file=sys.stderr)
            for agent in available_agents:
                print(f"  {agent}", file=sys.stderr)
            raise typer.Exit(1)

    output_error(detail)
    raise typer.Exit(1)


# --- Context Output Formatters ---


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output.

    Format: TASK:<id>|<status>|P<priority>|<type>|<complexity>
    OBJECTIVE:<objective>
    SPIRIT_ANTI:<anti-patterns>
    CONSTRAINTS[N]:<constraint1>|<constraint2>|...
    DONE_WHEN[N]:<item1>|<item2>|...
    """
    lines = []
    task_id = task.get("id", "unknown")
    status = task.get("status", "pending")
    priority = task.get("priority", 3)
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"

    lines.append(f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}")

    decisions_count = len(task.get("decisions") or [])
    lines.append(f"WORKFLOW:decisions:{decisions_count}")

    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{objective}")

    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")

    constraints = task.get("constraints") or []
    if constraints:
        lines.append(f"CONSTRAINTS[{len(constraints)}]:{' | '.join(constraints)}")

    done_when = task.get("done_when") or []
    if done_when:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")

    # Add context block if present (files_to_modify, files_to_create, risks, references)
    context = task.get("context") or {}
    if context:
        context_parts = []
        if files_mod := context.get("files_to_modify"):
            context_parts.append(f"modify:{','.join(files_mod)}")
        if files_create := context.get("files_to_create"):
            context_parts.append(f"create:{','.join(files_create)}")
        if risks := context.get("risks"):
            context_parts.append(f"risks:{len(risks)}")
        if refs := context.get("references"):
            context_parts.append(f"refs:{len(refs)}")
        if testing := context.get("testing_strategy"):
            context_parts.append(f"testing:{testing[:50]}")
        if context_parts:
            lines.append(f"CONTEXT:{' | '.join(context_parts)}")

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
        lines.append(f"{d_id}:{title}→{outcome}")

    return "\n".join(lines)


def format_context_subtasks(subtasks: list[dict[str, Any]]) -> str:
    """Format subtasks with steps inline for context output.

    Shows ALL details - full descriptions, all steps for all subtasks.

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
        phase = subtask.get("phase") or ""
        # Full description - no truncation
        desc = subtask.get("description") or ""
        step_summary = subtask.get("step_summary", {})
        step_done = step_summary.get("completed", 0)
        step_total = step_summary.get("total", 0)

        phase_prefix = f"[{phase}] " if phase else ""
        lines.append(f"{subtask_id:5} {passes} {phase_prefix}{desc} [{step_done}/{step_total}]")

        # Include steps for ALL subtasks - check both key names
        steps = subtask.get("steps") or subtask.get("steps_from_table") or []
        for step in steps:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            # Full step description - no truncation
            step_desc = step.get("description") or ""
            lines.append(f"  {step_num}. {step_pass} {step_desc}")

            # Show verification details if present
            verify_cmd = step.get("verify_command")
            expected_out = step.get("expected_output")
            if verify_cmd:
                lines.append(f"       verify: {verify_cmd}")
            if expected_out:
                lines.append(f"       expect: {expected_out}")

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
        title = b.get("title") or ""
        lines.append(f"{b_id}|{status}|{title}")

    return "\n".join(lines)


def format_context_log(progress_log: list[str] | str | None) -> str:
    """Format progress log for context output (last 3 entries).

    Format: LOG[total]
    <log entry preview, max 100 chars>
    """
    if not progress_log:
        return ""

    if isinstance(progress_log, str):
        entries = [e.strip() for e in progress_log.split("\n") if e.strip()]
    else:
        entries = progress_log

    if not entries:
        return ""

    recent_logs = entries[-3:]
    lines = [f"LOG[{len(entries)}]"]
    for log in recent_logs:
        log_preview = str(log)[:100]
        if len(str(log)) > 100:
            log_preview += "..."
        lines.append(f"  {log_preview}")

    return "\n".join(lines)


def output_context(
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]] | None = None,
) -> None:
    """Output full task context in TOON format.

    Combines task header, decisions, subtasks with steps, and blockers.
    """
    if _compact_output:
        sections = [
            format_context_task(task),
            format_context_decisions(task.get("decisions") or []),
            format_context_subtasks(subtasks),
        ]

        if blockers:
            sections.append(format_context_blockers(blockers))

        if task.get("progress_log"):
            sections.append(format_context_log(task["progress_log"]))

        print("\n".join(s for s in sections if s))
    else:
        output_json(
            {
                "task": task,
                "subtasks": subtasks,
                "blockers": blockers or [],
            }
        )
