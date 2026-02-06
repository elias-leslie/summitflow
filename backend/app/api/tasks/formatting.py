"""Tasks API - TOON formatting and hints.

Handles token-optimized output notation (TOON) formatting for tasks
and navigation hints generation.
"""

from __future__ import annotations

from ...schemas.tasks import TaskResponse


def toon_format_task(task: TaskResponse) -> str:
    """Convert TaskResponse to TOON (Token-Optimized Output Notation) format.

    Format: ID|STATUS|PRIORITY|TYPE|COMPLEXITY|DONE/TOTAL|CRITERIA|DECISIONS|TITLE
    Example: task-abc123|running|P2|task|STANDARD|0/6|criteria:19|decisions:0|Add TOON format
    """
    # Calculate done/total from subtask_summary if available
    done_total = "0/0"
    if task.subtask_summary:
        done_total = f"{task.subtask_summary.completed}/{task.subtask_summary.total}"

    # Format criteria count
    criteria_str = f"criteria:{task.criteria_count or 0}"

    # Format decisions count
    decisions_count = len(task.decisions) if task.decisions else 0
    decisions_str = f"decisions:{decisions_count}"

    # Format priority
    priority_str = f"P{task.priority}"

    # Complexity (default to empty if not set)
    complexity_str = task.complexity or ""

    # Truncate title to 80 chars max
    title = task.title[:80] if task.title else ""

    return f"{task.id}|{task.status}|{priority_str}|{task.task_type}|{complexity_str}|{done_total}|{criteria_str}|{decisions_str}|{title}"


def toon_format(task: TaskResponse) -> str:
    """Public API for TOON formatting - alias for toon_format_task."""
    return toon_format_task(task)


def get_hints(tasks: list[TaskResponse], project_id: str, endpoint_type: str = "list") -> list[str]:
    """Generate navigation hints based on task state.

    Args:
        tasks: List of task responses
        project_id: Current project ID
        endpoint_type: Type of endpoint (list, ready, blocked)

    Returns:
        List of hint strings with API URLs for next actions
    """
    hints: list[str] = []
    base_url = f"http://localhost:8001/api/projects/{project_id}"

    if not tasks:
        hints.append(f"No tasks found. Create one: POST {base_url}/tasks")
        return hints

    # Count by status
    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1

    # Suggest based on endpoint type and task states
    if endpoint_type == "ready":
        if tasks:
            first = tasks[0]
            hints.append(f"Full context: GET {base_url}/tasks/{first.id}/context")
            hints.append(f"Start task: PATCH {base_url}/tasks/{first.id}/status")
    elif endpoint_type == "blocked":
        hints.append(f"View ready tasks: GET {base_url}/tasks/ready")
        if tasks:
            first = tasks[0]
            hints.append(f"View blockers: GET {base_url}/tasks/{first.id}/dependencies")
    else:
        # General list hints - always include context hint first
        first = tasks[0]
        hints.append(f"Full context: GET {base_url}/tasks/{first.id}/context")
        if status_counts.get("pending", 0) > 0:
            hints.append(f"View ready tasks: GET {base_url}/tasks/ready")
        if status_counts.get("running", 0) > 0:
            hints.append(f"Filter running: GET {base_url}/tasks?status=running")
        if len(tasks) >= 50:
            hints.append(f"More results: GET {base_url}/tasks?offset=50")

    return hints


def toon_format_task_list(tasks: list[TaskResponse], endpoint_type: str = "list") -> str:
    """Convert task list to TOON format.

    Format:
    ENDPOINT:PREFIX:TOTAL
    task lines...

    Example for ready endpoint:
    READY:3
    task-abc123|pending|P2|task|STANDARD|0/6|criteria:19|decisions:0|Add TOON format
    """
    prefix_map = {"ready": "READY", "blocked": "BLOCKED", "list": "TASKS"}

    prefix = prefix_map.get(endpoint_type, "TASKS")
    lines = [f"{prefix}:{len(tasks)}"]

    for task in tasks:
        lines.append(toon_format_task(task))

    return "\n".join(lines)
