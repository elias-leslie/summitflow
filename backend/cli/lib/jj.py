"""Jujutsu helpers for st-owned VCS workflows."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JJ_TIMEOUT_SECONDS = 300
JJ_GLOBAL_ARGS = [
    "--no-pager",
    "--config",
    'ui.editor="true"',
    "--config",
    'ui.paginate="never"',
    "--config",
    'ui.diff-editor=":builtin"',
]
CURRENT_REV_TEMPLATE = (
    'change_id.short() ++ "\\t" ++ commit_id.short() ++ "\\t" ++ '
    'if(empty, "empty", "nonempty") ++ "\\t" ++ '
    'if(conflict, "conflict", "clean") ++ "\\t" ++ '
    'description.first_line() ++ "\\n"'
)
LOG_TEMPLATE = (
    'change_id.short() ++ "\\t" ++ commit_id.short() ++ "\\t" ++ '
    'author.email() ++ "\\t" ++ committer.timestamp().format("%Y-%m-%d %H:%M:%S") ++ "\\t" ++ '
    'description.first_line() ++ "\\n"'
)
OP_LOG_TEMPLATE = 'id.short() ++ "\\t" ++ description.first_line() ++ "\\n"'
BOOKMARK_TEMPLATE = 'bookmarks ++ "\\n"'


class JJError(RuntimeError):
    """Raised when jj is unavailable or a jj command fails."""


@dataclass(frozen=True)
class JJRevisionInfo:
    change_id: str
    commit_id: str
    empty: bool
    conflict: bool
    description: str


@dataclass(frozen=True)
class JJRepoStatus:
    repo: str
    path: str
    branch: str
    colocated: bool
    state: str
    described: bool
    conflicted: bool
    unpublished: int
    change_id: str = "-"
    commit_id: str = "-"


def jj_binary() -> str:
    """Return the jj binary path or raise a clear error."""
    binary = shutil.which("jj")
    if not binary:
        raise JJError("jj is not installed or not on PATH")
    return binary


def run_jj(
    repo: Path,
    args: list[str],
    *,
    timeout: int = JJ_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run jj non-interactively in repo."""
    command = [jj_binary(), *JJ_GLOBAL_ARGS, *args]
    return subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def run_git(repo: Path, args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run git for compatibility checks around a colocated jj repo."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def current_git_repo() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise JJError("not inside a git repository")
    return Path(result.stdout.strip())


def is_colocated(repo: Path) -> bool:
    return (repo / ".jj").is_dir() and (repo / ".git").exists()


def _git_branch(repo: Path) -> str:
    branch = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return branch or "HEAD"


def _first_local_bookmark(repo: Path, revset: str) -> str:
    result = run_jj(repo, ["log", "--no-graph", "-r", revset, "-T", BOOKMARK_TEMPLATE])
    if result.returncode != 0:
        return ""
    for token in result.stdout.split():
        if "@" not in token:
            return token
    return ""


def display_branch(repo: Path, git_branch: str | None = None) -> str:
    """Return a useful branch/bookmark label for colocated jj workspaces."""
    branch = git_branch or _git_branch(repo)
    if branch != "HEAD" or not is_colocated(repo):
        return branch
    return (
        _first_local_bookmark(repo, "@")
        or _first_local_bookmark(repo, "@-")
        or _first_local_bookmark(repo, "heads(ancestors(@) & bookmarks())")
        or "HEAD"
    )


def _require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise JJError(f"{action} failed: {detail}")


def init_colocated(repo: Path) -> dict[str, Any]:
    """Initialize jj colocation for an existing clean Git repository."""
    if is_colocated(repo):
        return {
            "repo": repo.name,
            "path": str(repo),
            "status": "SKIP",
            "reason": "already_colocated",
        }
    if not (repo / ".git").exists():
        raise JJError(f"{repo} is not a git repository")
    if (repo / ".jj").exists():
        raise JJError(f"{repo} has .jj but is not colocated")

    status = run_git(repo, ["status", "--short"])
    _require_success(status, "git status")
    if status.stdout.strip():
        raise JJError(f"refusing to initialize jj in dirty repository {repo}")

    result = run_jj(repo, ["git", "init", "--colocate", "."])
    _require_success(result, "jj git init --colocate")
    summary = status_summary(repo)
    return {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "state": summary.state,
        "change_id": summary.change_id,
        "commit_id": summary.commit_id,
        "operation_id": latest_operation_id(repo),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def revision_info(repo: Path, revision: str = "@") -> JJRevisionInfo:
    result = run_jj(repo, ["log", "--no-graph", "-r", revision, "-T", CURRENT_REV_TEMPLATE])
    _require_success(result, f"jj revision {revision}")
    line = result.stdout.strip("\n")
    parts = line.split("\t", 4)
    if len(parts) != 5:
        raise JJError(f"unexpected jj revision output: {line!r}")
    return JJRevisionInfo(
        change_id=parts[0],
        commit_id=parts[1],
        empty=parts[2] == "empty",
        conflict=parts[3] == "conflict",
        description=parts[4],
    )


def current_revision_info(repo: Path) -> JJRevisionInfo:
    return revision_info(repo, "@")


def unpublished_count(repo: Path) -> int:
    result = run_jj(repo, ["log", "-r", "remote_bookmarks(remote=origin)..(@ & ~empty())", "--count"])
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def status_summary(repo: Path) -> JJRepoStatus:
    git_branch = _git_branch(repo)
    branch = display_branch(repo, git_branch)
    if not is_colocated(repo):
        return JJRepoStatus(
            repo=repo.name,
            path=str(repo),
            branch=branch,
            colocated=False,
            state="not_colocated",
            described=False,
            conflicted=False,
            unpublished=0,
        )

    status = run_jj(repo, ["status"])
    _require_success(status, "jj status")
    info = current_revision_info(repo)
    unpublished = unpublished_count(repo)
    has_changes = "The working copy has no changes." not in status.stdout
    described = bool(info.description.strip())
    if info.conflict:
        state = "conflicted"
    elif not info.empty and not described:
        state = "undescribed"
    elif has_changes or not info.empty:
        state = "described" if described else "dirty"
    elif unpublished:
        state = "unpublished"
    else:
        state = "clean"
    return JJRepoStatus(
        repo=repo.name,
        path=str(repo),
        branch=branch,
        colocated=True,
        state=state,
        described=described,
        conflicted=info.conflict,
        unpublished=unpublished,
        change_id=info.change_id,
        commit_id=info.commit_id,
    )


def format_status_line(status: JJRepoStatus) -> str:
    return (
        f"{status.repo[:15].ljust(15)} {status.branch[:15].ljust(15)} "
        f"jj:{'yes' if status.colocated else 'no'} state:{status.state} "
        f"described:{str(status.described).lower()} "
        f"conflicts:{str(status.conflicted).lower()} unpublished:{status.unpublished} "
        f"change:{status.change_id} commit:{status.commit_id}"
    )


def run_checks(repo: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["st", "check", "--quick", "--changed-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=JJ_TIMEOUT_SECONDS,
        check=False,
    )
    return result.returncode == 0, (result.stdout + "\n" + result.stderr).strip()


def latest_operation_id(repo: Path) -> str:
    result = run_jj(repo, ["op", "log", "--no-graph", "-n", "1", "-T", OP_LOG_TEMPLATE])
    if result.returncode != 0:
        return ""
    return result.stdout.split("\t", 1)[0].strip()


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
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish the current jj revision under a deterministic bookmark."""
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    info = revision_info(repo, revision)
    if not info.description.strip():
        raise JJError(f"refusing to publish {revision} without a description")
    if info.conflict:
        raise JJError(f"refusing to publish conflicted revision {revision}")

    if run_quality_gate:
        ok, detail = run_checks(repo)
        if not ok:
            raise JJError(f"quality gates failed before jj push: {detail[-1200:]}")

    resolved_bookmark = task_bookmark(task_id, bookmark) or display_branch(repo)
    if resolved_bookmark == "HEAD":
        raise JJError("bookmark or task id is required when no current bookmark is available")
    set_result = run_jj(repo, ["bookmark", "set", resolved_bookmark, "-r", revision])
    _require_success(set_result, "jj bookmark set")

    push_args = [
        "git",
        "push",
        "--remote",
        remote,
        "--bookmark",
        resolved_bookmark,
        "--allow-empty-description",
    ]
    if dry_run:
        push_args.append("--dry-run")
    push_result = run_jj(repo, push_args)
    _require_success(push_result, "jj git push")

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
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    if not message.strip():
        raise JJError("commit message is required for jj-backed commit")
    if push and skip_checks:
        raise JJError("refusing to publish jj revision with --skip-checks")

    selected_paths = _normalize_selected_paths(repo, paths)
    split = run_jj(repo, ["split", "-m", message, "--", *selected_paths])
    _require_success(split, "jj split")
    info = revision_info(repo, "@-")
    result: dict[str, Any] = {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "change_id": info.change_id,
        "commit_id": info.commit_id,
        "message": message,
        "pushed": False,
        "selected_paths": selected_paths,
        "working_copy": "remaining",
    }
    if push:
        publish = publish_current_revision(
            repo,
            task_id=task_id,
            bookmark=bookmark,
            revision="@-",
            run_quality_gate=not skip_checks,
        )
        result.update(publish)
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
        _require_success(delete_result, "jj bookmark delete")

    push_args = ["git", "push", "--remote", remote, "--deleted"]
    if dry_run:
        push_args.append("--dry-run")
    push_result = run_jj(repo, push_args)
    _require_success(push_result, "jj git push deleted")

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
    if not is_colocated(repo):
        raise JJError(f"{repo} is not a jj-colocated repository")
    if not message.strip():
        raise JJError("commit message is required for jj-backed commit")
    if push and skip_checks:
        raise JJError("refusing to publish jj revision with --skip-checks")
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
        return {
            "repo": repo.name,
            "path": str(repo),
            "status": "SKIP",
            "reason": "clean",
            "pushed": False,
        }

    describe = run_jj(repo, ["describe", "-m", message])
    _require_success(describe, "jj describe")
    info = current_revision_info(repo)
    result: dict[str, Any] = {
        "repo": repo.name,
        "path": str(repo),
        "status": "SUCCESS",
        "change_id": info.change_id,
        "commit_id": info.commit_id,
        "message": message,
        "pushed": False,
    }
    if push:
        publish = publish_current_revision(
            repo,
            task_id=task_id,
            bookmark=bookmark,
            run_quality_gate=not skip_checks,
        )
        result.update(publish)
        new_working_copy = run_jj(repo, ["new"])
        _require_success(new_working_copy, "jj new")
        result["working_copy"] = "advanced"
    return result
