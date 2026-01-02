"""Git worktree commands for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from ..output import console, output_error, output_json, output_success

app = typer.Typer(help="Git worktree management")

WORKTREE_BASE = Path("/tmp/summitflow-worktrees")


def _get_worktrees_from_git() -> list[dict]:
    """Get worktrees from git worktree list."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(Path.home() / "summitflow"),
        )
        if result.returncode != 0:
            return []

        worktrees = []
        current: dict = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[9:]
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
            elif line.startswith("branch "):
                current["branch"] = line[7:]

        if current:
            worktrees.append(current)

        return worktrees
    except Exception:
        return []


@app.command("list")
def list_worktrees(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List active git worktrees.

    Shows worktrees in /tmp/summitflow-worktrees/ with linked task info.

    Examples:
        st worktree list
        st worktree list --json
    """
    # Get worktrees from git
    git_worktrees = _get_worktrees_from_git()

    # Filter to summitflow worktrees
    worktrees = [w for w in git_worktrees if "summitflow-worktrees" in w.get("path", "")]

    # Note: Future enhancement could query running tasks with worktree_path
    # in build_state to show task associations

    # Extract task_id from worktree directory names
    for w in worktrees:
        path = w.get("path", "")
        # Worktree directories are named like: {project_id}/{task_id}
        parts = path.split("/")
        if len(parts) >= 2:
            potential_task_id = parts[-1]
            if potential_task_id.startswith("task-"):
                w["task_id"] = potential_task_id

    if json_output:
        output_json(worktrees)
        return

    if not worktrees:
        console.print("[dim]No active worktrees found.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Git Worktrees", show_header=True, header_style="bold")
    table.add_column("Path", style="cyan")
    table.add_column("Branch", no_wrap=True)
    table.add_column("Task ID", no_wrap=True)
    table.add_column("Status")

    for w in worktrees:
        path = w.get("path", "")
        branch = w.get("branch", "").replace("refs/heads/", "")
        task_id = w.get("task_id", "-")
        exists = os.path.exists(path)
        status = "[green]active[/]" if exists else "[red]orphaned[/]"

        table.add_row(path, branch, task_id, status)

    console.print(table)


@app.command()
def prune(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Clean up orphaned worktrees.

    Removes worktree metadata for directories that no longer exist.

    Examples:
        st worktree prune
        st worktree prune --dry-run
    """
    # Run git worktree prune
    try:
        args = ["git", "worktree", "prune"]
        if dry_run:
            args.append("--dry-run")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(Path.home() / "summitflow"),
        )

        if json_output:
            output_json(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            return

        if result.returncode == 0:
            if dry_run:
                if result.stdout:
                    console.print("[yellow]Would prune:[/]")
                    console.print(result.stdout)
                else:
                    console.print("[dim]No orphaned worktrees to prune.[/dim]")
            else:
                output_success("Pruned orphaned worktree metadata")
        else:
            output_error(f"Failed to prune: {result.stderr}")

    except Exception as e:
        output_error(f"Failed to prune worktrees: {e}")
        raise typer.Exit(1) from None

    # Also clean up empty directories in worktree base
    if not dry_run and WORKTREE_BASE.exists():
        for project_dir in WORKTREE_BASE.iterdir():
            if project_dir.is_dir():
                for task_dir in project_dir.iterdir():
                    if task_dir.is_dir() and not any(task_dir.iterdir()):
                        task_dir.rmdir()
                        console.print(f"[dim]Removed empty: {task_dir}[/dim]")
                if not any(project_dir.iterdir()):
                    project_dir.rmdir()
                    console.print(f"[dim]Removed empty: {project_dir}[/dim]")
