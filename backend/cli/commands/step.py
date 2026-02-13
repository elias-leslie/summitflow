"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from . import step_bulk, step_defect, step_operations

app = typer.Typer(help="Step management commands")


@app.command("pass")
def pass_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    already_verified: Annotated[bool, typer.Option("--already-verified")] = False,
) -> None:
    """Mark step as passed (runs verify_command unless --already-verified)."""
    step_operations.pass_step(subtask_id, step_number, task_id, already_verified=already_verified)


@app.command("new")
def new_step(
    subtask_id: str,
    description: str,
    verify_command: Annotated[str, typer.Option("--verify", "-v")],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Create single step with verification."""
    step_operations.new_step(subtask_id, description, verify_command, task_id)


@app.command("update")
def update_step(
    subtask_id: str,
    step_number: int,
    verify_command: Annotated[str | None, typer.Option("--verify", "-v")] = None,
    description: Annotated[str | None, typer.Option("--desc", "-d")] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Update step description (verify is immutable)."""
    step_operations.update_step(
        subtask_id, step_number, description, verify_command, task_id
    )


@app.command("add")
def add_steps(
    subtask_id: str,
    descriptions: list[str] | None = None,
    verify_command: Annotated[str | None, typer.Option("--verify", "-v")] = None,
    json_input: Annotated[str | None, typer.Option("--json")] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Add steps (positional with shared verify or --json for per-step)."""
    step_bulk.add_steps(
        subtask_id, descriptions, verify_command, json_input, task_id
    )


@app.command("delete")
def delete_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    force: Annotated[bool, typer.Option("--force", "-f")] = False,
) -> None:
    """Delete step (--force required if passed)."""
    step_operations.delete_step(subtask_id, step_number, task_id, force)


@app.command("defect")
def mark_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step: Annotated[int | None, typer.Option("--fix", "-f")] = None,
    verify_command: Annotated[str | None, typer.Option("--verify", "-v")] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark step as plan defect (inline fix with -v or --fix N)."""
    step_defect.mark_plan_defect(
        subtask_id, step_number, fix_step, verify_command, task_id
    )


@app.command("list", hidden=True)
def list_removed() -> None:
    """Removed: use st context --subtask instead."""
    typer.echo("Removed. Use: st context <task-id> --subtask X.Y", err=True)
    raise typer.Exit(1)


@app.command("create", hidden=True)
def create_removed() -> None:
    """Removed: use st step new instead."""
    typer.echo("Removed. Use: st step new <subtask> <desc> -v <cmd>", err=True)
    raise typer.Exit(1)


@app.command("insert", hidden=True)
def insert_removed() -> None:
    """Removed: use st step add instead."""
    typer.echo("Removed. Use: st step add <subtask> <desc> --at N", err=True)
    raise typer.Exit(1)
