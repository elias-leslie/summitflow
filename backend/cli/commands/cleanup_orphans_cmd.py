"""Orphan task branch cleanup command bodies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from app.utils._git_branches import assess_orphan_task_branches

from ..output import output_error
from .cleanup_salvage import recover_orphan_task, validate_salvage_candidate


def task_display_token(item: object) -> str:
    """Return stable inspect-orphans task token from shared assessment truth."""
    task_token = getattr(item, "task_token", None)
    if isinstance(task_token, str) and task_token.startswith("task:"):
        return task_token.removeprefix("task:")
    task_status = getattr(item, "task_status", None)
    resolution = getattr(item, "resolution", None)
    return "unreadable" if resolution == "review" and task_status is None else (task_status or "missing")


AssessOrphans = Callable[[Path], list[Any]]
RecoverOrphan = Callable[[Path, Any, str], Any]


def inspect_orphans_command(
    repos: list[Path],
    *,
    all_projects: bool,
    assess: AssessOrphans = assess_orphan_task_branches,
) -> None:
    lines: list[str] = []
    salvage_count = review_count = 0
    for repo_path in repos:
        repo_lines, salvage, review = _repo_orphan_lines(repo_path, assess)
        lines.extend(repo_lines)
        salvage_count += salvage
        review_count += review
    scope = "all" if all_projects else "current"
    typer.echo(f"ORPHAN-REVIEW[{scope}]:total={len(lines)} salvage={salvage_count} review={review_count}")
    for line in lines:
        typer.echo(line)


def _repo_orphan_lines(repo_path: Path, assess: AssessOrphans) -> tuple[list[str], int, int]:
    lines: list[str] = []
    salvage_count = review_count = 0
    for item in assess(repo_path):
        salvage_count += int(item.resolution == "salvage")
        review_count += int(item.resolution != "salvage")
        lines.append(_format_orphan_line(repo_path, item))
    return lines, salvage_count, review_count


def _format_orphan_line(repo_path: Path, item: Any) -> str:
    flags = []
    if item.resolution == "salvage":
        flags.append("task_missing")
    elif task_display_token(item) == "unreadable":
        flags.append("task_unreadable")
    if item.has_node_modules_artifact:
        flags.append("node_modules_artifact")
    return (
        f"{repo_path.name} {item.task_id} branch:{item.branch_name} "
        f"resolution:{item.resolution} task:{task_display_token(item)} "
        f"ahead:{item.commits_ahead} behind:{item.commits_behind} files:{item.files_changed} "
        f"flags:{','.join(flags) if flags else '-'}"
    )


def salvage_orphan_command(
    task_id: str,
    repos: list[Path],
    *,
    assess: AssessOrphans = assess_orphan_task_branches,
    recover: RecoverOrphan = recover_orphan_task,
) -> None:
    """Recover a missing-task orphan branch into a normal task checkpoint."""
    match = next(
        ((repo, item) for repo in repos for item in assess(repo) if item.task_id == task_id),
        None,
    )
    if match is None:
        output_error(
            f"No unresolved orphan branch found for {task_id}. "
            "Use `st cleanup inspect-orphans` to find salvage candidates."
        )
        raise typer.Exit(1)

    repo_path, item = match
    if not validate_salvage_candidate(item, task_id):
        raise typer.Exit(1)
    recover(repo_path, item, task_id)
