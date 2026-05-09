"""Jujutsu repository status and initialization helpers."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .jj_common import (
    BOOKMARK_TEMPLATE,
    CURRENT_REV_TEMPLATE,
    JJ_TIMEOUT_SECONDS,
    OP_LOG_TEMPLATE,
    JJError,
    JJRepoStatus,
    JJRevisionInfo,
    is_colocated,
    require_success,
    run_git,
    run_jj,
)


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


def init_colocated(repo: Path) -> dict[str, Any]:
    """Initialize jj colocation for an existing clean Git repository."""
    if is_colocated(repo):
        return {"repo": repo.name, "path": str(repo), "status": "SKIP", "reason": "already_colocated"}
    if not (repo / ".git").exists():
        raise JJError(f"{repo} is not a git repository")
    if (repo / ".jj").exists():
        raise JJError(f"{repo} has .jj but is not colocated")

    status = run_git(repo, ["status", "--short"])
    require_success(status, "git status")
    if status.stdout.strip():
        raise JJError(f"refusing to initialize jj in dirty repository {repo}")

    result = run_jj(repo, ["git", "init", "--colocate", "."])
    require_success(result, "jj git init --colocate")
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
    require_success(result, f"jj revision {revision}")
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
    """Count locally-unpublished revisions, excluding the post-publish empty ceremony commit.

    `jj new` after publish leaves an empty undescribed `@` (or `@-` once new
    work starts on top); that's canonical clean state, not "ahead". Filter
    those out of the range, not just the leaf, so the surface doesn't
    false-positive after every publish.
    """
    revset = "remote_bookmarks(remote=origin)..@ ~ (empty() & description(exact:\"\"))"
    result = run_jj(repo, ["log", "-r", revset, "--count"])
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
    require_success(status, "jj status")
    info = current_revision_info(repo)
    unpublished = unpublished_count(repo)
    state = _status_state(status.stdout, info, unpublished)
    return JJRepoStatus(
        repo=repo.name,
        path=str(repo),
        branch=branch,
        colocated=True,
        state=state,
        described=bool(info.description.strip()),
        conflicted=info.conflict,
        unpublished=unpublished,
        change_id=info.change_id,
        commit_id=info.commit_id,
    )


def _status_state(status_stdout: str, info: JJRevisionInfo, unpublished: int) -> str:
    has_changes = "The working copy has no changes." not in status_stdout
    described = bool(info.description.strip())
    if info.conflict:
        return "conflicted"
    if not info.empty and not described:
        return "undescribed"
    if has_changes or not info.empty:
        return "described" if described else "dirty"
    if unpublished:
        return "unpublished"
    return "clean"


def format_status_line(status: JJRepoStatus) -> str:
    return (
        f"{status.repo[:15].ljust(15)} {status.branch[:15].ljust(15)} "
        f"jj:{'yes' if status.colocated else 'no'} state:{status.state} "
        f"described:{str(status.described).lower()} "
        f"conflicts:{str(status.conflicted).lower()} unpublished:{status.unpublished} "
        f"change:{status.change_id} commit:{status.commit_id}"
    )


def run_checks(repo: Path, *, paths: Sequence[str] = ()) -> tuple[bool, str]:
    env = None
    if paths:
        env = {**dict(os.environ), "ST_CHECK_CHANGED_FILES": "\n".join(paths)}
    result = subprocess.run(
        ["st", "check", "--quick", "--changed-only"],
        cwd=repo,
        env=env,
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
