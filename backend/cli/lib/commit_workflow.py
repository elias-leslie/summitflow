"""Canonical st commit workflow."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
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


def _normalize_paths(repo: Path, paths: Sequence[str]) -> list[str]:
    """Resolve user-supplied paths to repo-relative posix strings."""
    repo_root = repo.resolve()
    selected: list[str] = []
    for raw in paths:
        value = raw.strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_absolute():
            try:
                value = path.resolve().relative_to(repo_root).as_posix()
            except ValueError as exc:
                raise CommitError(f"path is outside repository: {raw}") from exc
        selected.append(value)
    if not selected:
        raise CommitError("at least one path is required for selective commit")
    return selected


def _selected_paths_dirty(repo: Path, paths: Sequence[str]) -> bool:
    """Return True if any of the selected paths has staged or unstaged changes."""
    result = run_git(repo, ["status", "--porcelain", "--", *paths])
    return bool(result.stdout.strip())


def _addable_paths(repo: Path, paths: Sequence[str]) -> list[str]:
    """Drop paths that git refuses to `add` (currently gitignored).

    Common case: user runs `git rm --cached file` then adds the file to
    `.gitignore`, then asks st commit to commit both. The .gitignore change
    is addable; the now-ignored file isn't (its deletion is already staged).
    Without this filter, `git add -- <paths>` errors on the ignored entry
    and aborts the whole commit.
    """
    addable: list[str] = []
    for path in paths:
        check = run_git(repo, ["check-ignore", "--quiet", "--", path])
        if check.returncode == 0:
            continue
        addable.append(path)
    return addable


def commit_git_revision(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
    paths: Sequence[str] = (),
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
    selected_paths: list[str] = []
    if paths:
        selected_paths = _normalize_paths(repo, paths)
        if not _selected_paths_dirty(repo, selected_paths):
            if not push:
                return {**result, "reason": "no_changes_in_selected_paths"}
            pushed = run_git(repo, push_args(repo))
            if pushed.returncode != 0:
                raise CommitError(pushed.stderr.strip() or pushed.stdout.strip() or "git push failed")
            return {**result, "reason": "no_changes_in_selected_paths", "pushed": True}
    elif not dirty(repo):
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
    if selected_paths:
        addable = _addable_paths(repo, selected_paths)
        if addable:
            add = run_git(repo, ["add", "--", *addable])
            if add.returncode != 0:
                raise CommitError(add.stderr.strip() or "git add failed")
    else:
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
    if selected_paths:
        result["selected_paths"] = selected_paths
    if push:
        pushed = run_git(repo, push_args(repo))
        if pushed.returncode != 0:
            raise CommitError(pushed.stderr.strip() or pushed.stdout.strip() or "git push failed")
        result["pushed"] = True
    if task_id:
        result["task_id"] = task_id
    return result


def _cleanup_after_publish(repo: Path, result: dict[str, Any], *, push: bool) -> dict[str, Any]:
    """Prune safe task refs after successful publication."""
    if not push or result.get("status") != "SUCCESS" or not result.get("pushed"):
        return result
    try:
        from cli.commands.cleanup_handlers import cleanup_safe_git_residue
    except Exception:
        return result
    try:
        counts = cleanup_safe_git_residue([repo], dry_run=False)
    except Exception:
        return result
    result["residue_pruned"] = sum(counts)
    result["residue_pruned_counts"] = {
        "legacy_registrations": counts[0],
        "orphan_merged": counts[1],
        "orphan_equivalent": counts[2],
        "orphan_closed": counts[3],
        "task_local": counts[4],
        "task_remote": counts[5],
    }
    return result


def _refresh_symbols_after_publish(repo: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Queue a targeted symbol reindex of the published commit's files.

    Bridges the bi-hourly sweep gap so fresh symbols are searchable
    immediately. Best-effort: a completed publish must never fail on this.
    """
    if result.get("status") != "SUCCESS" or not result.get("pushed"):
        return result
    sha = str(result.get("commit_id") or result.get("sha") or "").strip()
    if not sha:
        return result
    try:
        from app.services.explorer.types.file_constants import SYMBOL_INDEX_EXTENSIONS
        from cli.client import STClient

        from .execution_context import resolve_checkout_project_id

        project_id = resolve_checkout_project_id(repo)
        if not project_id:
            return result
        changed = run_git(repo, ["diff-tree", "-r", "--name-only", "--no-commit-id", sha]).stdout.splitlines()
        paths = [p for p in changed if p and Path(p).suffix.lower() in SYMBOL_INDEX_EXTENSIONS]
        if not paths:
            return result
        client = STClient(project_id=project_id)
        client.post(client._url("/explorer/symbols/refresh"), json={"paths": paths})
        result["symbol_refresh_queued"] = len(paths)
    except Exception:
        return result
    return result


def commit_repo(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
    bookmark: str = "",
    paths: Sequence[str] = (),
) -> dict[str, Any]:
    if push and skip_checks:
        raise CommitError("refusing to publish with --skip-checks")
    if (repo / ".jj").is_dir():
        try:
            result = commit_current_revision(
                repo,
                message=message,
                task_id=task_id,
                push=push,
                skip_checks=skip_checks,
                bookmark=bookmark,
                paths=paths,
            )
            return _refresh_symbols_after_publish(repo, _cleanup_after_publish(repo, result, push=push))
        except JJError as exc:
            raise CommitError(str(exc)) from exc
    result = commit_git_revision(
        repo,
        message=message,
        task_id=task_id,
        push=push,
        skip_checks=skip_checks,
        paths=paths,
    )
    return _refresh_symbols_after_publish(repo, _cleanup_after_publish(repo, result, push=push))
