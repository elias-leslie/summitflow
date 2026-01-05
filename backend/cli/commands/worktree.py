"""Git worktree commands for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer

from ..config import get_config
from ..output import output_error, output_json, output_success

app = typer.Typer(help="Git worktree management")

# Base directory for all worktrees (project-agnostic)
WORKTREE_BASE = Path("/tmp/st-worktrees")


def _get_project_root() -> Path:
    """Get the current project's root directory."""
    config = get_config()
    if config.project_root:
        return Path(config.project_root)
    # Fallback: try to find git root from cwd
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    # Last resort: use cwd
    return Path.cwd()


def _get_worktrees_from_git(project_root: Path) -> list[dict[str, Any]]:
    """Get worktrees from git worktree list.

    Args:
        project_root: Root directory of the git repository
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            return []

        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
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
    all_projects: Annotated[
        bool, typer.Option("--all", "-a", help="Show worktrees for all projects")
    ] = False,
) -> None:
    """List active git worktrees for the current project.

    Shows worktrees in /tmp/st-worktrees/{project_id}/ with linked task info.

    Examples:
        st worktree list
        st worktree list --all
    """
    config = get_config()
    project_root = _get_project_root()

    # Get worktrees from git
    git_worktrees = _get_worktrees_from_git(project_root)

    # Filter to st-worktrees
    if all_projects:
        # Show all worktrees under st-worktrees base
        worktrees = [w for w in git_worktrees if "st-worktrees" in w.get("path", "")]
    else:
        # Filter to current project's worktrees
        project_worktree_dir = str(WORKTREE_BASE / config.project_id)
        worktrees = [w for w in git_worktrees if w.get("path", "").startswith(project_worktree_dir)]

    # Extract task_id and project_id from worktree directory names
    for w in worktrees:
        path = w.get("path", "")
        # Worktree directories are named like: /tmp/st-worktrees/{project_id}/{task_id}
        parts = path.split("/")
        if len(parts) >= 2:
            potential_task_id = parts[-1]
            if potential_task_id.startswith("task-"):
                w["task_id"] = potential_task_id
            # Project ID is second to last
            if len(parts) >= 3:
                w["project_id"] = parts[-2]

        # Add status
        w["status"] = "active" if os.path.exists(path) else "orphaned"

    output_json({"worktrees": worktrees, "project_id": config.project_id})


@app.command()
def prune(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    all_projects: Annotated[
        bool, typer.Option("--all", "-a", help="Prune worktrees for all projects")
    ] = False,
) -> None:
    """Clean up orphaned worktrees.

    Removes worktree metadata for directories that no longer exist.

    Examples:
        st worktree prune
        st worktree prune --dry-run
        st worktree prune --all
    """
    project_root = _get_project_root()

    # Run git worktree prune
    try:
        args = ["git", "worktree", "prune"]
        if dry_run:
            args.append("--dry-run")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )

        if result.returncode == 0:
            if dry_run:
                output_json({"dry_run": True, "would_prune": result.stdout or None})
            else:
                output_success("Pruned orphaned worktree metadata")

                # Also clean up empty directories in worktree base
                removed_dirs = []
                if WORKTREE_BASE.exists():
                    config = get_config()
                    if all_projects:
                        # Clean all project directories
                        dirs_to_check = list(WORKTREE_BASE.iterdir())
                    else:
                        # Only clean current project's directory
                        project_dir = WORKTREE_BASE / config.project_id
                        dirs_to_check = [project_dir] if project_dir.exists() else []

                    for project_dir in dirs_to_check:
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
