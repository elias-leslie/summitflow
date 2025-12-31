"""Task commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_error, output_success, output_task, output_task_list

app = typer.Typer(help="Task management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command()
def create(
    title: str,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[str, typer.Option("-t", "--type")] = "task",
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    plan: Annotated[str | None, typer.Option("--plan")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a new task.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
    """
    client = STClient()

    data: dict = {
        "title": title,
        "task_type": task_type,
        "priority": priority,
    }
    if description:
        data["description"] = description
    if labels:
        data["labels"] = labels.split(",")
    if parent:
        data["parent_task_id"] = parent

    try:
        task = client.create_task(data)
    except APIError as e:
        _handle_api_error(e)
        return

    if plan:
        # Update with plan_content
        try:
            import json

            plan_content = json.loads(plan)
            task = client.update_task(task["id"], plan_content=plan_content)
        except (json.JSONDecodeError, APIError) as e:
            output_error(f"Failed to set plan: {e}")

    output_task(task, json_output)
    if not json_output:
        output_success(f"Created task {task['id']}")


@app.command("list")
def list_tasks(
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List tasks with optional filters.

    Examples:
        st list --status pending
        st list -t bug -p 1
        st list --labels "complexity:small" --json
    """
    client = STClient()

    labels_list = labels.split(",") if labels else None

    try:
        result = client.list_tasks(
            status=status,
            task_type=task_type,
            priority=priority,
            labels=labels_list,
            limit=limit,
        )
    except APIError as e:
        _handle_api_error(e)
        return

    output_task_list(result["tasks"], json_output)


@app.command()
def ready(
    limit: Annotated[int, typer.Option("--limit")] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List tasks ready to work on (not blocked).

    Examples:
        st ready
        st ready --limit 10 --json
    """
    client = STClient()

    try:
        result = client.list_ready(limit=limit)
    except APIError as e:
        _handle_api_error(e)
        return

    output_task_list(result["tasks"], json_output, title="Ready Tasks")


@app.command()
def show(
    task_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show task details.

    Examples:
        st show task-abc123
        st show task-abc123 --json
    """
    client = STClient()

    try:
        task = client.get_task(task_id)
    except APIError as e:
        _handle_api_error(e)
        return

    output_task(task, json_output)


@app.command()
def update(
    task_id: str,
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    move_to: Annotated[str | None, typer.Option("--move-to")] = None,
    plan: Annotated[str | None, typer.Option("--plan")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Update a task.

    Examples:
        st update task-abc123 --status running
        st update task-abc123 -p 1 -l "complexity:large"
        st update task-abc123 --move-to other-project
    """
    client = STClient()

    # Handle status update separately (uses /status endpoint)
    if status:
        try:
            task = client.update_status(task_id, status)
            output_task(task, json_output)
            if not json_output:
                output_success(f"Updated task {task_id} status to: {status}")
            return
        except APIError as e:
            _handle_api_error(e)
            return

    # Build update data
    updates: dict = {}
    if priority is not None:
        updates["priority"] = priority
    if labels:
        updates["labels"] = labels.split(",")
    if task_type:
        updates["task_type"] = task_type
    if title:
        updates["title"] = title
    if description:
        updates["description"] = description
    if move_to:
        updates["project_id"] = move_to
    if plan:
        import json

        try:
            updates["plan_content"] = json.loads(plan)
        except json.JSONDecodeError as e:
            output_error(f"Invalid plan JSON: {e}")
            raise typer.Exit(1) from None

    if not updates:
        output_error("No updates specified")
        raise typer.Exit(1)

    try:
        task = client.update_task(task_id, **updates)
    except APIError as e:
        _handle_api_error(e)
        return

    output_task(task, json_output)
    if not json_output:
        output_success(f"Updated task {task_id}")


@app.command()
def close(
    task_id: str,
    reason: Annotated[str | None, typer.Option("-r", "--reason")] = None,
    force: Annotated[bool, typer.Option("-f", "--force")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Close a task (mark as completed).

    Examples:
        st close task-abc123 -r "Fixed the bug"
        st close task-abc123 --force
    """
    client = STClient()

    try:
        task = client.close_task(task_id, reason=reason, force=force)
    except APIError as e:
        _handle_api_error(e)
        return

    output_task(task, json_output)
    if not json_output:
        output_success(f"Closed task {task_id}")


@app.command()
def claim(
    task_id: str,
    lock: Annotated[int, typer.Option("--lock")] = 30,
    release: Annotated[bool, typer.Option("--release")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Claim or release a task.

    Examples:
        st claim task-abc123 --lock 60
        st claim task-abc123 --release
    """
    client = STClient()

    try:
        if release:
            task = client.release_task(task_id)
            if not json_output:
                output_success(f"Released task {task_id}")
        else:
            task = client.claim_task(task_id, lock_minutes=lock)
            if not json_output:
                output_success(f"Claimed task {task_id} for {lock} minutes")
    except APIError as e:
        _handle_api_error(e)
        return

    output_task(task, json_output)


@app.command()
def delete(
    task_id: str,
    force: Annotated[bool, typer.Option("-f", "--force")] = False,
) -> None:
    """Delete a task.

    Examples:
        st delete task-abc123
        st delete task-abc123 --force
    """
    if not force:
        confirm = typer.confirm(f"Delete task {task_id}?")
        if not confirm:
            raise typer.Abort()

    client = STClient()

    try:
        client.delete_task(task_id)
    except APIError as e:
        _handle_api_error(e)
        return

    output_success(f"Deleted task {task_id}")
