"""Task commands for the CLI."""

from __future__ import annotations

from datetime import UTC
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
    blocked: Annotated[bool, typer.Option("--blocked")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List tasks ready to work on (not blocked).

    Use --blocked to show blocked tasks instead.

    Examples:
        st ready
        st ready --blocked
        st ready --limit 10 --json
    """
    client = STClient()

    try:
        if blocked:
            # Get pending tasks and filter to blocked ones
            result = client.list_tasks(status="pending", limit=limit * 2)
            tasks = result.get("tasks", [])

            # Filter to tasks that have blocking dependencies
            blocked_tasks = []
            blockers_map: dict[str, list[str]] = {}  # blocker_id -> [blocked_task_ids]

            for task in tasks:
                task_id = task["id"]
                deps = client.list_dependencies(task_id)

                # Find incomplete blocking dependencies
                blocking = [
                    d
                    for d in deps
                    if d.get("dependency_type") == "blocks"
                    and d.get("depends_on_status") not in ("completed", "cancelled")
                ]

                if blocking:
                    task["blockers"] = blocking
                    blocked_tasks.append(task)

                    # Track which tasks each blocker blocks
                    for b in blocking:
                        blocker_id = b.get("depends_on_task_id", "")
                        if blocker_id not in blockers_map:
                            blockers_map[blocker_id] = []
                        blockers_map[blocker_id].append(task_id)

            blocked_tasks = blocked_tasks[:limit]

            if json_output:
                from ..output import output_json

                output_json({"tasks": blocked_tasks, "blockers_impact": blockers_map})
                return

            if not blocked_tasks:
                from ..output import console

                console.print("[dim]No blocked tasks found.[/dim]")
                return

            from ..output import console

            console.print(f"\n[bold]Blocked Tasks[/bold] ({len(blocked_tasks)} tasks)\n")

            # Group by blocker for impact view
            console.print("[bold]Blockers Impact:[/bold]")
            for blocker_id, blocked_ids in sorted(blockers_map.items(), key=lambda x: -len(x[1])):
                console.print(f"  [red]{blocker_id}[/] blocks {len(blocked_ids)} task(s)")

            console.print("\n[bold]Blocked Tasks:[/bold]")
            for task in blocked_tasks:
                task_id = task["id"]
                title = task.get("title", "")[:40]
                blockers = task.get("blockers", [])
                blocker_ids = [b.get("depends_on_task_id", "") for b in blockers]
                console.print(f"  [cyan]{task_id}[/]: {title}")
                console.print(f"    [dim]Blocked by: {', '.join(blocker_ids)}[/]")
        else:
            result = client.list_ready(limit=limit)
            output_task_list(result["tasks"], json_output, title="Ready Tasks")
    except APIError as e:
        _handle_api_error(e)
        return


@app.command()
def show(
    task_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show task details with subtask progress.

    Examples:
        st show task-abc123
        st show task-abc123 --json
    """
    client = STClient()

    try:
        task = client.get_task(task_id)
        subtask_data = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        _handle_api_error(e)
        return

    # Merge subtask info into task for output
    subtasks = subtask_data.get("subtasks", [])
    summary = subtask_data.get("summary", {})

    if json_output:
        task["subtasks"] = subtasks
        task["subtask_summary"] = summary
        output_task(task, json_output)
        return

    # Output task details
    output_task(task, json_output)

    # Output subtask progress if subtasks exist
    if subtasks:
        from ..output import console

        total = summary.get("total", len(subtasks))
        completed = summary.get("completed", 0)
        pct = summary.get("progress_percent", 0.0)
        next_id = summary.get("next_subtask_id", "")

        console.print(f"\n[bold]Subtasks:[/bold] {completed}/{total} ({pct:.0f}%)")
        if next_id:
            console.print(f"[dim]Next: {next_id}[/dim]")

        for s in subtasks:
            passes = s.get("passes", False)
            icon = "[green]✓[/]" if passes else "[dim]○[/]"
            sid = s.get("subtask_id", "")
            desc = s.get("description", "")[:60]
            step_sum = s.get("step_summary", {})
            step_info = ""
            if step_sum and step_sum.get("total", 0) > 0:
                step_info = f" [{step_sum['completed']}/{step_sum['total']}]"
            console.print(f"  {icon} {sid}: {desc}{step_info}")


@app.command()
def update(
    task_id: str,
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    add_label: Annotated[list[str] | None, typer.Option("--add-label")] = None,
    remove_label: Annotated[list[str] | None, typer.Option("--remove-label")] = None,
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
        st update task-abc123 --add-label auto-generated
        st update task-abc123 --remove-label tier:1 --add-label tier:2
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

    # Handle label modifications
    if add_label or remove_label:
        # Fetch current task to get existing labels
        try:
            current_task = client.get_task(task_id)
            current_labels = set(current_task.get("labels", []) or [])
        except APIError as e:
            _handle_api_error(e)
            return

        # Remove labels first, then add
        if remove_label:
            for label in remove_label:
                current_labels.discard(label)

        if add_label:
            for label in add_label:
                current_labels.add(label)

        updates["labels"] = list(current_labels)
    elif labels:
        # Full replacement
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
        # Provide helpful hints for common errors
        detail = e.detail.lower()
        hints: list[str] = []

        if "criteria" in detail or "unverified" in detail:
            hints.append("Hint: Use --force to bypass criteria validation")
            hints.append("Hint: Or verify pending criteria first")

        if "capability" in detail:
            hints.append("Hint: Run 'st capability verify <id>' to check test status")

        if "status" in detail or "transition" in detail:
            hints.append("Hint: Check task status with 'st show <id>'")
            hints.append("Hint: Use 'st cancel <id>' for non-terminal states")

        if "not found" in detail:
            hints.append("Hint: Verify task ID with 'st list'")

        output_error(e.detail)
        from ..output import console

        for hint in hints:
            console.print(f"[yellow]{hint}[/]")
        raise typer.Exit(1) from None

    output_task(task, json_output)
    if not json_output:
        output_success(f"Closed task {task_id}")


@app.command()
def cancel(
    task_id: str,
    reason: Annotated[str, typer.Option("-r", "--reason")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Cancel a task (mark as cancelled from any state).

    Use this for tasks that are invalid, obsolete, or no longer needed.
    Works from any non-terminal state (pending, running, paused, failed).

    Examples:
        st cancel task-abc123 -r "Invalid: file doesn't exist"
        st cancel task-abc123 --reason "Obsolete: already fixed"
    """
    client = STClient()

    try:
        task = client.cancel_task(task_id)
    except APIError as e:
        _handle_api_error(e)
        return

    output_task(task, json_output)
    if not json_output:
        output_success(f"Cancelled task {task_id}: {reason}")


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


@app.command()
def bug(
    title: str,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    from_task: Annotated[str | None, typer.Option("--from")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a bug task (shorthand for create -t bug).

    If --from is specified, creates a discovered-from dependency and
    inherits domain labels from the parent task.

    Examples:
        st bug "Fix null pointer exception" -p 1
        st bug "Missing validation" --from task-abc123
        st bug "Type error in auth" -l "complexity:small,domains:backend"
    """
    client = STClient()

    # If --from specified, fetch parent to inherit domains
    inherited_labels: list[str] = []
    if from_task:
        try:
            parent = client.get_task(from_task)
            parent_labels = parent.get("labels", [])
            # Inherit domain labels
            for label in parent_labels:
                if label.startswith("domains:"):
                    inherited_labels.append(label)
        except APIError:
            pass  # If parent not found, continue without inheriting

    # Build labels list
    all_labels: list[str] = []
    if labels:
        all_labels.extend(labels.split(","))
    # Add inherited labels that aren't already present
    for label in inherited_labels:
        if label not in all_labels:
            all_labels.append(label)

    data: dict = {
        "title": title,
        "task_type": "bug",
        "priority": priority,
    }
    if description:
        data["description"] = description
    if all_labels:
        data["labels"] = all_labels

    try:
        task = client.create_task(data)
    except APIError as e:
        _handle_api_error(e)
        return

    # Create discovered-from dependency if --from specified
    if from_task:
        try:
            client.add_dependency(task["id"], from_task, dep_type="discovered-from")
            if not json_output:
                output_success(f"Linked {task['id']} → {from_task} (discovered-from)")
        except APIError as e:
            output_error(f"Created task but failed to add dependency: {e.detail}")

    output_task(task, json_output)
    if not json_output:
        output_success(f"Created bug {task['id']}")


@app.command()
def exec(
    task_id: str,
    agent: Annotated[str, typer.Option("--agent")] = "claude",
    worktree: Annotated[bool, typer.Option("--worktree")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Start execution of a task via API.

    Triggers the autonomous execution system to work on the task.

    Examples:
        st exec task-abc123
        st exec task-abc123 --agent gemini
        st exec task-abc123 --worktree
    """
    client = STClient()

    try:
        result = client.start_execution(task_id, agent_type=agent, use_worktree=worktree)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        from ..output import output_json

        output_json(result)
    else:
        session_id = result.get("session_id", "")
        status = result.get("status", "")
        worktree_path = result.get("worktree_path")

        output_success(f"Started execution for {task_id}")
        from ..output import console

        console.print(f"  Session ID: [cyan]{session_id}[/]")
        console.print(f"  Status: {status}")
        if worktree_path:
            console.print(f"  Worktree: {worktree_path}")


@app.command()
def log(
    task_id: str,
    message: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Append a log entry to a task's progress log.

    A timestamp is automatically prepended to the message.

    Examples:
        st log task-abc123 "Started working on feature"
        st log task-abc123 "Fixed issue with validation"
    """
    from datetime import datetime

    client = STClient()

    # Add timestamp prefix
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{timestamp}] {message}"

    try:
        result = client.append_log(task_id, entry)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        from ..output import output_json

        output_json(result)
    else:
        output_success(f"Logged to {task_id}: {message}")
