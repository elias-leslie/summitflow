"""Rich output formatters for CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from .client import APIError

console = Console()

# Status colors
STATUS_COLORS = {
    "pending": "yellow",
    "running": "blue",
    "paused": "cyan",
    "completed": "green",
    "failed": "red",
}

# Priority labels
PRIORITY_LABELS = {
    0: "[red bold]P0[/]",
    1: "[red]P1[/]",
    2: "[yellow]P2[/]",
    3: "[dim]P3[/]",
    4: "[dim]P4[/]",
}


def output_json(data: Any) -> None:
    """Output data as formatted JSON."""
    console.print_json(json.dumps(data, default=str))


def output_task(task: dict[str, Any], json_mode: bool = False) -> None:
    """Output a single task with status-colored Panel.

    Args:
        task: Task dict
        json_mode: If True, output as JSON
    """
    if json_mode:
        output_json(task)
        return

    status = task.get("status", "pending")
    color = STATUS_COLORS.get(status, "white")
    priority = task.get("priority", 2)
    priority_label = PRIORITY_LABELS.get(priority, f"P{priority}")

    title = f"[{color}]{task['id']}[/] {priority_label} [{task.get('task_type', 'task')}]"

    content_lines = [
        f"[bold]{task['title']}[/bold]",
        "",
        f"Status: [{color}]{status}[/]",
    ]

    if task.get("description"):
        content_lines.append(f"\n{task['description'][:200]}...")

    if task.get("labels"):
        content_lines.append(f"\nLabels: {', '.join(task['labels'])}")

    panel = Panel(
        "\n".join(content_lines),
        title=title,
        border_style=color,
    )
    console.print(panel)


def _extract_tier(labels: list[str] | None) -> str:
    """Extract tier from labels list."""
    if not labels:
        return "-"
    for label in labels:
        if label.startswith("tier:"):
            return label.split(":")[1]
    return "-"


def output_task_list(
    tasks: list[dict[str, Any]],
    json_mode: bool = False,
    title: str = "Tasks",
    show_tier: bool = False,
) -> None:
    """Output a list of tasks as a Rich Table.

    Args:
        tasks: List of task dicts
        json_mode: If True, output as JSON
        title: Table title
        show_tier: If True, show tier column
    """
    if json_mode:
        output_json({"tasks": tasks, "total": len(tasks)})
        return

    if not tasks:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Pri", justify="center", no_wrap=True)
    if show_tier:
        table.add_column("Tier", justify="center", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")
    table.add_column("Labels", style="dim")

    for task in tasks:
        status = task.get("status", "pending")
        color = STATUS_COLORS.get(status, "white")
        priority = task.get("priority", 2)
        priority_label = PRIORITY_LABELS.get(priority, f"P{priority}")

        # Truncate title
        title_text = task.get("title", "")[:50]
        if len(task.get("title", "")) > 50:
            title_text += "..."

        # Format labels (exclude tier if showing separately)
        task_labels = task.get("labels", [])
        if show_tier:
            task_labels = [lbl for lbl in task_labels if not lbl.startswith("tier:")]
        labels = ", ".join(task_labels[:2])
        if len(task_labels) > 2:
            labels += "..."

        row = [
            task["id"],
            priority_label,
        ]
        if show_tier:
            tier = _extract_tier(task.get("labels"))
            tier_display = f"[cyan]{tier}[/]" if tier != "-" else "[dim]-[/]"
            row.append(tier_display)

        row.extend(
            [
                f"[dim]{task.get('task_type', 'task')}[/dim]",
                title_text,
                f"[{color}]{status}[/]",
                labels,
            ]
        )

        table.add_row(*row)

    console.print(table)


def output_deps(deps: list[dict[str, Any]], json_mode: bool = False) -> None:
    """Output dependency list.

    Args:
        deps: List of dependency dicts
        json_mode: If True, output as JSON
    """
    if json_mode:
        output_json(deps)
        return

    if not deps:
        console.print("[dim]No dependencies.[/dim]")
        return

    table = Table(title="Dependencies", show_header=True, header_style="bold")
    table.add_column("Depends On", style="cyan")
    table.add_column("Type", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")

    for dep in deps:
        status = dep.get("depends_on_status", "pending")
        color = STATUS_COLORS.get(status, "white")

        table.add_row(
            dep["depends_on_task_id"],
            dep.get("dependency_type", "blocks"),
            dep.get("depends_on_title", "")[:40],
            f"[{color}]{status}[/]",
        )

    console.print(table)


def output_capabilities(caps: list[dict[str, Any]], json_mode: bool = False) -> None:
    """Output capability table.

    Args:
        caps: List of capability dicts
        json_mode: If True, output as JSON
    """
    if json_mode:
        output_json(caps)
        return

    if not caps:
        console.print("[dim]No capabilities found.[/dim]")
        return

    table = Table(title="Capabilities", show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Status", justify="center")
    table.add_column("Pri", justify="center", no_wrap=True)

    for cap in caps:
        status = cap.get("status", "pending")
        color = STATUS_COLORS.get(status, "white")
        priority = cap.get("priority", 2)
        priority_label = PRIORITY_LABELS.get(priority, f"P{priority}")

        table.add_row(
            cap.get("capability_id", ""),
            cap.get("name", "")[:40],
            f"[{color}]{status}[/]",
            priority_label,
        )

    console.print(table)


def output_tests(tests: list[dict[str, Any]], json_mode: bool = False) -> None:
    """Output test table.

    Args:
        tests: List of test dicts
        json_mode: If True, output as JSON
    """
    if json_mode:
        output_json(tests)
        return

    if not tests:
        console.print("[dim]No tests found.[/dim]")
        return

    table = Table(title="Tests", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Type", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Capability")

    for test in tests:
        status = test.get("last_status", "unknown")
        color = {"passed": "green", "failed": "red", "error": "red"}.get(status, "dim")

        table.add_row(
            test.get("name", "")[:50],
            test.get("type", ""),
            f"[{color}]{status}[/]",
            test.get("capability_id", "")[:20] or "-",
        )

    console.print(table)


def output_error(message: str) -> None:
    """Output error message in red."""
    console.print(f"[red bold]Error:[/] {message}")


def output_success(message: str) -> None:
    """Output success message in green."""
    console.print(f"[green]{message}[/]")


def output_warning(message: str) -> None:
    """Output warning message in yellow."""
    console.print(f"[yellow]{message}[/]")


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit.

    Args:
        e: APIError exception from client
    """
    output_error(e.detail)
    raise typer.Exit(1)
