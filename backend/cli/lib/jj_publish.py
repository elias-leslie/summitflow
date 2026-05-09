"""Jujutsu publish and commit helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .jj_common import JJError, JJRevisionInfo, is_colocated, require_success, run_jj
from .jj_status import (
    current_revision_info,
    display_branch,
    latest_operation_id,
    revision_info,
    run_checks,
    status_summary,
)


def task_bookmark(task_id: str, bookmark: str = "") -> str:
    if bookmark:
        return bookmark
    if task_id:
        return f"task/{task_id}"
    return ""


def publish_current_revision(
    repo: Path,
    *,
    task_id: str = "",
    bookmark: str = "",
    revision: str = "@",
    remote: str = "origin",
    run_quality_gate: bool = True,
    check_paths: Sequence[str] = (),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish the current jj revision under a deterministic bookmark."""
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    info = revision_info(repo, revision)
    _validate_publishable_revision(info, revision)

    if run_quality_gate:
        ok, detail = run_checks(repo, paths=check_paths)
        if not ok:
            raise JJError(f"quality gates failed before jj push: {detail[-1200:]}")

    resolved_bookmark = task_bookmark(task_id, bookmark) or display_branch(repo)
    if resolved_bookmark == "HEAD":
        raise JJError("bookmark or task id is required when no current bookmark is available")
    bookmark_set = run_jj(repo, ["bookmark", "set", resolved_bookmark, "-r", revision])
    if bookmark_set.returncode != 0:
        detail = (bookmark_set.stderr or bookmark_set.stdout or "").strip()
        if "Refusing to move bookmark backwards or sideways" in detail:
            raise JJError(
                f"sideways revision: @ has diverged from {resolved_bookmark}. "
                f"Run `jj rebase -d {resolved_bookmark}` and resolve any conflicts, then retry st commit."
            )
        raise JJError(f"jj bookmark set failed: {detail}")

    push_result = run_jj(repo, _push_args(remote, resolved_bookmark, dry_run))
    require_success(push_result, "jj git push")
    return {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "change_id": info.change_id,
        "commit_id": info.commit_id,
        "operation_id": latest_operation_id(repo),
        "bookmark": resolved_bookmark,
        "pushed": not dry_run,
        "stdout": push_result.stdout.strip(),
        "stderr": push_result.stderr.strip(),
    }


def _validate_publishable_revision(info: JJRevisionInfo, revision: str) -> None:
    if not info.description.strip():
        raise JJError(f"refusing to publish {revision} without a description")
    if info.conflict:
        raise JJError(f"refusing to publish conflicted revision {revision}")


def _push_args(remote: str, bookmark: str, dry_run: bool) -> list[str]:
    args = ["git", "push", "--remote", remote, "--bookmark", bookmark, "--allow-empty-description"]
    if dry_run:
        args.append("--dry-run")
    return args


def _normalize_selected_paths(repo: Path, paths: Sequence[str]) -> list[str]:
    selected: list[str] = []
    repo_root = repo.resolve()
    for raw in paths:
        value = raw.strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_absolute():
            try:
                value = path.resolve().relative_to(repo_root).as_posix()
            except ValueError as exc:
                raise JJError(f"path is outside repository: {raw}") from exc
        selected.append(value)
    if not selected:
        raise JJError("at least one path is required for selective commit")
    return selected


def _fileset_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _selected_path_fileset(repo: Path, path: str) -> str:
    prefix = "root" if (repo / path).is_dir() else "root-file"
    return f"{prefix}:{_fileset_string_literal(path)}"


def _selected_path_filesets(repo: Path, paths: Sequence[str]) -> list[str]:
    return [_selected_path_fileset(repo, path) for path in paths]


def _ensure_selected_paths_have_changes(repo: Path, filesets: Sequence[str], paths: Sequence[str]) -> None:
    result = run_jj(repo, ["diff", "--name-only", *filesets])
    require_success(result, "jj diff selected paths")
    if result.stdout.strip():
        return
    raise JJError(f"selected paths have no changes: {', '.join(paths)}")


def commit_selected_paths(
    repo: Path,
    *,
    message: str,
    paths: Sequence[str],
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
    bookmark: str = "",
) -> dict[str, Any]:
    """Split selected paths from @, describe that revision, and optionally publish it."""
    _validate_commit(repo, message, push, skip_checks)
    selected_paths = _normalize_selected_paths(repo, paths)
    selected_filesets = _selected_path_filesets(repo, selected_paths)
    _ensure_selected_paths_have_changes(repo, selected_filesets, selected_paths)
    require_success(run_jj(repo, ["split", "-m", message, "--", *selected_filesets]), "jj split")
    info = revision_info(repo, "@-")
    result = _commit_result(repo, info, message, selected_paths=selected_paths, working_copy="remaining")
    if push:
        result.update(
            publish_current_revision(
                repo,
                task_id=task_id,
                bookmark=bookmark,
                revision="@-",
                run_quality_gate=not skip_checks,
                check_paths=selected_paths,
            )
        )
        result["selected_paths"] = selected_paths
        result["working_copy"] = "remaining"
    return result


def delete_task_bookmark(
    repo: Path,
    *,
    task_id: str = "",
    bookmark: str = "",
    remote: str = "origin",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete a task bookmark locally and push the deletion to the Git remote."""
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    resolved_bookmark = task_bookmark(task_id, bookmark)
    if not resolved_bookmark:
        raise JJError("task id or bookmark is required for bookmark cleanup")

    delete_result = run_jj(repo, ["bookmark", "delete", resolved_bookmark])
    delete_detail = (delete_result.stdout + delete_result.stderr).strip()
    if delete_result.returncode != 0 and "No such bookmark" not in delete_detail:
        require_success(delete_result, "jj bookmark delete")

    push_args = ["git", "push", "--remote", remote, "--deleted"]
    if dry_run:
        push_args.append("--dry-run")
    push_result = run_jj(repo, push_args)
    require_success(push_result, "jj git push deleted")
    return {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "bookmark": resolved_bookmark,
        "operation_id": latest_operation_id(repo),
        "deleted": not dry_run,
        "stdout": (delete_result.stdout + push_result.stdout).strip(),
        "stderr": (delete_result.stderr + push_result.stderr).strip(),
    }


def commit_current_revision(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
    bookmark: str = "",
    paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Describe the current jj revision and optionally publish it."""
    _validate_commit(repo, message, push, skip_checks)
    if paths:
        return commit_selected_paths(
            repo,
            message=message,
            paths=paths,
            task_id=task_id,
            push=push,
            skip_checks=skip_checks,
            bookmark=bookmark,
        )

    before = status_summary(repo)
    if before.state == "clean" and before.unpublished == 0:
        return {"repo": repo.name, "path": str(repo), "status": "SKIP", "reason": "clean", "pushed": False}

    require_success(run_jj(repo, ["describe", "-m", message]), "jj describe")
    info = current_revision_info(repo)
    result = _commit_result(repo, info, message)
    if push:
        result.update(publish_current_revision(repo, task_id=task_id, bookmark=bookmark, run_quality_gate=not skip_checks))
        require_success(run_jj(repo, ["new"]), "jj new")
        result["working_copy"] = "advanced"
    return result


def _validate_commit(repo: Path, message: str, push: bool, skip_checks: bool) -> None:
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    if not message.strip():
        raise JJError("commit message is required for jj-backed commit")
    if push and skip_checks:
        raise JJError("refusing to publish jj revision with --skip-checks")


def _commit_result(repo: Path, info: JJRevisionInfo, message: str, **extra: Any) -> dict[str, Any]:
    result = {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "change_id": info.change_id,
        "commit_id": info.commit_id,
        "message": message,
        "pushed": False,
    }
    result.update(extra)
    return result
