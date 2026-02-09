"""Task listing command implementation."""

from __future__ import annotations

from ..client import APIError, STClient
from ..output import handle_api_error, output_json, output_task_list


def list_tasks_command(
    status: str | None,
    task_type: str | None,
    priority: int | None,
    tier: int | None,
    labels: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """List tasks with optional filters.

    Examples:
        st list --status pending
        st list -t bug -p 1
        st list --tier 1
        st list --labels "complexity:small"
        st list --type refactor --json | jq '.tasks[0].id'
    """
    client = STClient()

    # Build labels list, adding tier filter if specified
    labels_list = labels.split(",") if labels else None
    if tier:
        tier_label = f"tier:{tier}"
        if labels_list:
            labels_list.append(tier_label)
        else:
            labels_list = [tier_label]

    try:
        result = client.list_tasks(
            status=status,
            task_type=task_type,
            priority=priority,
            labels=labels_list,
            limit=limit,
        )
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json({"tasks": result["tasks"], "total": len(result["tasks"])})
    else:
        output_task_list(result["tasks"])
