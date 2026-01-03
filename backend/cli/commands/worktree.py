"""Git worktree commands for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from ..output import output_error, output_json, output_success

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
def list_worktrees() -> None:
    """List active git worktrees.

    Shows worktrees in /tmp/summitflow-worktrees/ with linked task info.

    Examples:
        st worktree list
    """
    # Get worktrees from git
    git_worktrees = _get_worktrees_from_git()

    # Filter to summitflow worktrees
    worktrees = [w for w in git_worktrees if "summitflow-worktrees" in w.get("path", "")]

    # Extract task_id from worktree directory names
    for w in worktrees:
        path = w.get("path", "")
        # Worktree directories are named like: {project_id}/{task_id}
        parts = path.split("/")
        if len(parts) >= 2:
            potential_task_id = parts[-1]
            if potential_task_id.startswith("task-"):
                w["task_id"] = potential_task_id

        # Add status
        w["status"] = "active" if os.path.exists(path) else "orphaned"

    output_json(worktrees)


@app.command()
def prune(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
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

        if result.returncode == 0:
            if dry_run:
                output_json({"dry_run": True, "would_prune": result.stdout or None})
            else:
                output_success("Pruned orphaned worktree metadata")

                # Also clean up empty directories in worktree base
                removed_dirs = []
                if WORKTREE_BASE.exists():
                    for project_dir in WORKTREE_BASE.iterdir():
                        if project_dir.is_dir():
                            for task_dir in project_dir.iterdir():
                                if task_dir.is_dir() and not any(task_dir.iterdir()):
                                    task_dir.rmdir()
                                    removed_dirs.append(str(task_dir))
                            if not any(project_dir.iterdir()):
                                project_dir.rmdir()
                                removed_dirs.append(str(project_dir))

                if removed_dirs:
                    output_json({"removed_empty_dirs": removed_dirs})
        else:
            output_error(f"Failed to prune: {result.stderr}")

    except Exception as e:
        output_error(f"Failed to prune worktrees: {e}")
        raise typer.Exit(1) from None
