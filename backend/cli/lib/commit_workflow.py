"""Canonical st commit workflow."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .jj import JJError, commit_current_revision
from .publish_workflow import PublishError, publish_git


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
    result = run_git(repo, ["status", "--porcelain"])
    if result.returncode != 0:
        raise CommitError(result.stderr.strip() or "cannot inspect working tree status")
    return bool(result.stdout.strip())


def run_checks(repo: Path, *, paths: Sequence[str] = ()) -> tuple[bool, str]:
    # Same canonical changed-file input used by the Jujutsu commit path.
    env = {**os.environ, "ST_CHECK_CHANGED_FILES": "\n".join(paths)} if paths else None
    result = subprocess.run(
        ["st", "check", "--check", "--changed-only"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    detail = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, detail[-1200:]


def outgoing_paths(repo: Path) -> list[str]:
    """Include committed-but-unpublished inputs, even with a clean working tree."""
    current = run_git(repo, ["branch", "--show-current"])
    if current.returncode != 0:
        raise CommitError(current.stderr.strip() or "cannot determine publication branch")
    # Native publication targets origin/current, regardless of @{upstream}.
    destination = f"refs/remotes/origin/{current.stdout.strip()}" if current.stdout.strip() else ""
    known = run_git(repo, ["rev-parse", "--verify", destination]) if destination else None
    args = (["diff", "--name-only", "-z", f"{destination}..HEAD"]
            if known is not None and known.returncode == 0 else ["ls-files", "-z"])
    result = run_git(repo, args)
    if result.returncode:
        raise CommitError(result.stderr.strip() or "cannot determine outgoing check scope")
    return sorted(set(item for item in result.stdout.split("\0") if item))


def _publish_revision(repo: Path, result: dict[str, Any], *, task_id: str, message: str) -> dict[str, Any]:
    sha = run_git(repo, ["rev-parse", "HEAD"])
    if sha.returncode or not sha.stdout.strip():
        raise CommitError("cannot resolve publication commit")
    try:
        return {**result, **publish_git(repo, sha=sha.stdout.strip(), task_id=task_id,
                                       message=message, run_git=run_git)}
    except PublishError as exc:
        raise CommitError(str(exc)) from exc


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
    if result.returncode != 0:
        raise CommitError(result.stderr.strip() or "cannot inspect selected working tree status")
    return bool(result.stdout.strip())


def _selected_changed_files(repo: Path, paths: Sequence[str]) -> list[str]:
    """Expand selected directories before passing the canonical gate its scope."""
    files: set[str] = set()
    for args in (
        ["diff", "--name-only", "-z", "HEAD", "--", *paths],
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *paths],
    ):
        result = run_git(repo, args)
        if result.returncode != 0:
            raise CommitError(result.stderr.strip() or "cannot resolve selected check paths")
        files.update(item for item in result.stdout.split("\0") if item)
    return sorted(files) or list(paths)


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



def _commit_selected_index(repo: Path, message: str, paths: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Commit staged selections without rescanning ignored worktree replacements."""
    patch = subprocess.run(["git", "diff", "--cached", "--binary", "--full-index", "--", *paths],
                           cwd=repo, capture_output=True, check=False)
    if patch.returncode != 0:
        raise CommitError(patch.stderr.decode(errors="replace").strip() or "cannot read selected staged changes")
    with tempfile.TemporaryDirectory(prefix="st-commit-index-") as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}

        def indexed(args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", *args], cwd=repo, env=env,
                                  text=True, capture_output=True, check=False)

        prepared = indexed(["read-tree", "HEAD"])
        if prepared.returncode != 0:
            raise CommitError(prepared.stderr.strip() or "cannot prepare selected commit index")
        # Keep the staged patch byte-for-byte: text-mode pipes normalize CRLF.
        applied = subprocess.run(["git", "apply", "--cached", "--binary", "-"], cwd=repo,
                                 env=env, input=patch.stdout, capture_output=True, check=False)
        if applied.returncode != 0:
            raise CommitError(applied.stderr.decode(errors="replace").strip() or "cannot apply selected staged changes")
        # Normal commit still runs every hook against the selected index.
        committed = indexed(["commit", "-m", message])
        if committed.returncode == 0:
            # Path-scoped reset updates only these index entries, including hook
            # changes. It never moves HEAD or touches the ignored local cache.
            reconciled = run_git(repo, ["reset", "--quiet", "HEAD", "--", *paths])
            if reconciled.returncode != 0:
                raise CommitError(reconciled.stderr.strip() or "commit created; selected index reconciliation failed")
        return committed


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
    selected_paths = _normalize_paths(repo, paths) if paths else []
    has_changes = _selected_paths_dirty(repo, selected_paths) if selected_paths else dirty(repo)
    if not has_changes and not push:
        return {**result, "reason": "no_changes_in_selected_paths" if selected_paths else "clean"}
    selected_files = _selected_changed_files(repo, selected_paths) if selected_paths and has_changes else []
    changed_scope = (selected_files if selected_paths else _selected_changed_files(repo, ["."])) if has_changes else []
    scope = sorted(set([*changed_scope, *(outgoing_paths(repo) if push else [])]))
    if not skip_checks and (has_changes or scope):
        ok, detail = run_checks(repo, paths=scope)
        if not ok:
            return {**result, "status": "BLOCKED", "reason": "quality_gates_failed", "detail": detail}
    if not has_changes:
        return _publish_revision(repo, {**result, "reason": "clean"}, task_id=task_id, message=message)
    if selected_paths:
        addable = _addable_paths(repo, selected_files)
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
    commit_args = ["commit", "-m", message]
    if selected_paths:
        commit_args.extend(["--only", "--", *selected_files])
    committed = (_commit_selected_index(repo, message, selected_files)
                 if selected_paths and len(addable) != len(selected_files)
                 else run_git(repo, commit_args))
    if committed.returncode != 0:
        raise CommitError(committed.stderr.strip() or committed.stdout.strip() or "git commit failed")
    sha = run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    result.update({"status": "SUCCESS", "sha": sha, "message": message})
    if selected_paths:
        result["selected_paths"] = selected_paths
    if push:
        result = _publish_revision(repo, result, task_id=task_id, message=message)
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
