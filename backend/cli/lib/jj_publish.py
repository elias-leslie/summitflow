"""Jujutsu publish and commit helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.services.git.outgoing import (
    OutgoingVerificationError,
    PushUpdate,
    live_destination_bases,
    verify_outgoing,
)

from .jj_common import JJError, JJRevisionInfo, is_colocated, require_success, run_git, run_jj
from .jj_status import (
    current_revision_info,
    latest_operation_id,
    revision_info,
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
    """Retired publication entry point; require the accepted-source publisher."""
    raise JJError(
        "publish an accepted source explicitly with "
        "st vcs publish --source ID --sha FULL_OID --now"
    )


def _verify_jj_outgoing(repo: Path, sha: str, bookmark: str, remote: str, *, deleting: bool = False) -> None:
    """JJ transports bypass Git hooks; verify the actual selected update here."""
    destination = run_git(repo, ["remote", "get-url", "--push", "--all", remote])
    require_success(destination, "resolve JJ publication destination")
    urls = destination.stdout.splitlines()
    if len(urls) != 1:
        raise JJError("JJ publication requires one unambiguous destination")
    # JJ versions differ in pushurl support: refuse ambiguous routing.
    fetch_url = run_git(repo, ["remote", "get-url", remote])
    require_success(fetch_url, "resolve JJ remote URL")
    if fetch_url.stdout.strip() != urls[0]:
        raise JJError("JJ publication requires identical fetch and push destinations")
    ref = "refs/heads/" + bookmark
    live = run_git(repo, ["ls-remote", "--refs", urls[0], ref])
    require_success(live, "inspect live JJ publication destination")
    lines = live.stdout.splitlines()
    if len(lines) > 1 or (lines and lines[0].split()[1:] != [ref]):
        raise JJError("Ambiguous live JJ destination ref")
    old = lines[0].split()[0] if lines else "0" * len(sha)
    if not deleting:
        current = run_git(repo, ["rev-parse", "--verify", ref + "^{commit}"])
        require_success(current, "resolve exact JJ bookmark")
        if current.stdout.strip() != sha:
            raise JJError("JJ publication bookmark changed after source verification")
        if lines:
            present = run_git(repo, ["cat-file", "-e", old + "^{commit}"])
            if present.returncode:
                require_success(run_git(repo, ["fetch", "--no-tags", urls[0], old]), "fetch exact JJ destination object")
    try:
        bases = live_destination_bases(repo, urls[0]) if not lines and not deleting else ()
        verify_outgoing(repo, urls[0], [PushUpdate("(delete)" if deleting else ref, sha, ref, old)], published_bases=bases)
    except OutgoingVerificationError as exc:
        raise JJError(str(exc)) from exc


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
    push: bool = False,
    skip_checks: bool = False,
    bookmark: str = "",
) -> dict[str, Any]:
    """Split selected paths from @ and describe a local checkpoint."""
    _validate_commit(repo, message, push, skip_checks)
    selected_paths = _normalize_selected_paths(repo, paths)
    selected_filesets = _selected_path_filesets(repo, selected_paths)
    _ensure_selected_paths_have_changes(repo, selected_filesets, selected_paths)
    require_success(run_jj(repo, ["split", "-m", message, "--", *selected_filesets]), "jj split")
    info = revision_info(repo, "@-")
    result = _commit_result(repo, info, message, selected_paths=selected_paths, working_copy="remaining")
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

    push_args = ["git", "push", "--remote", remote, "--bookmark", "exact:" + resolved_bookmark]
    if dry_run:
        push_args.append("--dry-run")
    else:
        _verify_jj_outgoing(repo, "0" * 40, resolved_bookmark, remote, deleting=True)
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
    push: bool = False,
    skip_checks: bool = False,
    bookmark: str = "",
    paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Describe the current jj revision as a local checkpoint."""
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
    return result


def _validate_commit(repo: Path, message: str, push: bool, skip_checks: bool) -> None:
    if push:
        raise JJError(
            "jj checkpoints are local; publish an accepted source explicitly with "
            "st vcs publish --source ID --sha FULL_OID --now"
        )
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    if not message.strip():
        raise JJError("commit message is required for jj-backed commit")


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
