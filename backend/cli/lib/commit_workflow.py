"""Canonical st commit workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .jj import JJError, commit_current_revision


class CommitError(RuntimeError):
    """Raised when commit workflow cannot run."""


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def current_repo() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise CommitError("not inside a git repository")
    return Path(result.stdout.strip())


def dirty(repo: Path) -> bool:
    return bool(run_git(repo, ["status", "--porcelain"]).stdout.strip())


def run_checks(repo: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["st", "check", "--quick", "--changed-only"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    detail = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, detail[-1200:]


def branch(repo: Path) -> str:
    return run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "HEAD"


def push_args(repo: Path) -> list[str]:
    args = ["push"]
    upstream = run_git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    current = branch(repo)
    if upstream.returncode != 0 and current not in {"HEAD", "main", "master"}:
        args.extend(["--set-upstream", "origin", current])
    return args


def commit_git_revision(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
) -> dict[str, Any]:
    if not message.strip():
        raise CommitError("commit message is required")
    if push and skip_checks:
        raise CommitError("refusing to publish with --skip-checks")
    result: dict[str, Any] = {
        "repo": repo.name,
        "path": str(repo),
        "status": "SKIP",
        "pushed": False,
    }
    if not dirty(repo):
        if not push:
            return {**result, "reason": "clean"}
        pushed = run_git(repo, push_args(repo))
        if pushed.returncode != 0:
            raise CommitError(pushed.stderr.strip() or pushed.stdout.strip() or "git push failed")
        return {**result, "reason": "clean", "pushed": True}
    if not skip_checks:
        ok, detail = run_checks(repo)
        if not ok:
            return {**result, "status": "BLOCKED", "reason": "quality_gates_failed", "detail": detail}
    add = run_git(repo, ["add", "-A"])
    if add.returncode != 0:
        raise CommitError(add.stderr.strip() or "git add failed")
    if run_git(repo, ["diff", "--cached", "--quiet"]).returncode == 0:
        return {**result, "reason": "no_staged_changes"}
    committed = run_git(repo, ["commit", "-m", message])
    if committed.returncode != 0:
        raise CommitError(committed.stderr.strip() or committed.stdout.strip() or "git commit failed")
    sha = run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    result.update({"status": "SUCCESS", "sha": sha, "message": message})
    if push:
        pushed = run_git(repo, push_args(repo))
        if pushed.returncode != 0:
            raise CommitError(pushed.stderr.strip() or pushed.stdout.strip() or "git push failed")
        result["pushed"] = True
    if task_id:
        result["task_id"] = task_id
    return result


def commit_repo(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
    bookmark: str = "",
) -> dict[str, Any]:
    if push and skip_checks:
        raise CommitError("refusing to publish with --skip-checks")
    if (repo / ".jj").is_dir():
        try:
            return commit_current_revision(
                repo,
                message=message,
                task_id=task_id,
                push=push,
                skip_checks=skip_checks,
                bookmark=bookmark,
            )
        except JJError as exc:
            raise CommitError(str(exc)) from exc
    return commit_git_revision(
        repo,
        message=message,
        task_id=task_id,
        push=push,
        skip_checks=skip_checks,
    )
