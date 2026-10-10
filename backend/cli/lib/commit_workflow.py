"""Canonical st commit workflow."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import Any

from . import coord, leases
from .acceptance import AcceptanceError, repo_lock, workspace_fingerprint
from .task_claims import TaskClaimRenewalError, renew_owned_claim


class CommitError(RuntimeError):
    """Raised when commit workflow cannot run."""


# Concurrent sessions share one repository mutation lock; a commit waits briefly
# for another session's commit/acceptance instead of failing immediately.
REPO_LOCK_WAIT_SECONDS = 60.0
REPO_LOCK_POLL_SECONDS = 2.0
# Checks rerun once when only files outside a --paths selection changed.
CHECK_ATTEMPTS = 2

COMMIT_PUBLICATION_GUIDANCE = (
    "st commit creates local checkpoints; publish an accepted source explicitly with "
    "st vcs publish --source ID --sha FULL_OID --now"
)


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


def run_checks(
    repo: Path,
    *,
    paths: Sequence[str] = (),
    full: bool = False,
) -> tuple[bool, str]:
    env = {**os.environ, "ST_CHECK_CHANGED_FILES": "\n".join(paths)} if paths else None
    result = subprocess.run(
        ["st", "check", "--check" if full else "--quick", "--changed-only"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    detail = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, detail[-1200:]


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
    head = run_git(repo, ["rev-parse", "--verify", "HEAD"])
    tracked = (["diff", "--name-only", "-z", "HEAD", "--", *paths] if head.returncode == 0
               else ["ls-files", "--cached", "-z", "--", *paths])
    for args in (
        tracked,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *paths],
    ):
        result = run_git(repo, args)
        if result.returncode != 0:
            raise CommitError(result.stderr.strip() or "cannot resolve selected check paths")
        files.update(item for item in result.stdout.split("\0") if item)
    return sorted(files) or list(paths)


def _checkout_snapshot(repo: Path) -> dict[str, str]:
    """Per-path state of dirty files (status, index blob, worktree blob) plus HEAD."""
    status = run_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status.returncode != 0:
        raise CommitError(status.stderr.strip() or "cannot inspect working tree status")
    codes: dict[str, str] = {}
    items = iter(status.stdout.split("\0"))
    for item in items:
        if len(item) < 4:
            continue
        codes[item[3:]] = item[:2]
        if item[0] in "RC":
            next(items, None)  # rename/copy source path
    snapshot = {"\0HEAD": run_git(repo, ["rev-parse", "-q", "--verify", "HEAD"]).stdout.strip()}
    if not codes:
        return snapshot
    staged = run_git(repo, ["--literal-pathspecs", "ls-files", "--stage", "-z", "--", *codes]).stdout.split("\0")
    index = {entry.split("\t", 1)[1]: entry.split()[1] for entry in staged if "\t" in entry}
    present = [path for path in codes if (repo / path).is_file()]
    hashed = subprocess.run(["git", "hash-object", "--no-filters", "--stdin-paths"], cwd=repo,
                            input="\n".join(present), text=True, capture_output=True, check=False)
    blobs = dict(zip(present, hashed.stdout.split(), strict=False)) if hashed.returncode == 0 else {}
    for path, code in codes.items():
        snapshot[path] = f"{code}:{index.get(path, '-')}:{blobs.get(path, '-')}"
    return snapshot


def _snapshot_changes(repo: Path, before: dict[str, str]) -> set[str]:
    """Paths whose state differs from ``before``, including files a new HEAD brought in."""
    after = _checkout_snapshot(repo)
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    changed.discard("\0HEAD")
    old_head, new_head = before["\0HEAD"], after["\0HEAD"]
    if old_head != new_head:
        if not old_head:
            return changed | {"<new HEAD>"}
        moved = run_git(repo, ["diff", "--name-only", "-z", old_head, new_head])
        changed.update(item for item in moved.stdout.split("\0") if item)
        if moved.returncode != 0:
            changed.add("<moved HEAD>")
    return changed


def _changed_detail(changed: set[str], scope: Sequence[str], *, retried: bool) -> str:
    """One-line reason naming what changed while checks ran."""
    if not changed:
        return "checkout inputs changed while checkpoint checks were running; retry the commit"
    inside = sorted(changed & set(scope))
    named = inside or sorted(changed)
    listed = ", ".join(named[:5]) + (f" (+{len(named) - 5} more)" if len(named) > 5 else "")
    if inside:
        return f"selected files changed while checks ran: {listed}; finish editing, then retry the commit"
    if retried:
        return f"files outside the selection kept changing across a rerun: {listed}; retry the commit"
    return f"checkout changed while checks ran: {listed}; retry the commit"


@contextmanager
def _commit_repo_lock(repo: Path) -> Iterator[None]:
    """Take the repository mutation lock, waiting briefly while another operation holds it."""
    deadline = time.monotonic() + REPO_LOCK_WAIT_SECONDS
    noticed = False
    while True:
        stack = ExitStack()
        try:
            stack.enter_context(repo_lock(repo, purpose="commit"))
        except AcceptanceError as exc:
            if not str(exc).startswith("repo_mutation_in_progress") or time.monotonic() >= deadline:
                raise
            if not noticed:
                print(f"st commit: another repository operation is running; waiting up to "
                      f"{REPO_LOCK_WAIT_SECONDS:.0f}s for it to finish", file=sys.stderr)
                noticed = True
            time.sleep(REPO_LOCK_POLL_SECONDS)
            continue
        with stack:
            yield
        return


def _require_foreign_leases_clear(repo: Path, changed_paths: Sequence[str]) -> None:
    """Keep a Git checkpoint from absorbing another agent's leased work."""
    if not changed_paths:
        return
    resolved = coord.project_for_path(repo)
    if resolved is None:
        return
    project_id, root = resolved
    for path in changed_paths:
        ok, holder = leases.check(project_id, path, project_root=str(root))
        if not ok and holder is not None:
            raise CommitError(
                f"cannot commit {path}: leased by another agent {holder.agent_id} "
                f"(task={holder.task_id or '--'}); coordinate or select only your own paths"
            )


def _release_committed_leases(repo: Path, committed: Sequence[str]) -> None:
    """Committed work is no longer in flight: drop the committer's file leases on it."""
    resolved = coord.project_for_path(repo)
    if resolved is None or not committed:
        return
    with suppress(OSError):
        leases.release_paths(resolved[0], [str(resolved[1] / path) for path in committed])


def _addable_paths(repo: Path, paths: Sequence[str]) -> list[str]:
    """Drop paths that git refuses to `add` (gitignored or already-staged deletions).

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
        # A `git rm` deletion is already staged and has no pathspec left to add.
        if (not (repo / path).exists()
                and run_git(repo, ["ls-files", "--error-unmatch", "--", path]).returncode != 0):
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

        prepared = indexed(["read-tree", "HEAD"] if run_git(repo, ["rev-parse", "--verify", "HEAD"]).returncode == 0
                           else ["read-tree", "--empty"])
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


def _follow_published_merge(repo: Path, result: dict[str, Any]) -> None:
    """Commit on top of the last publication merge so the next one stays incremental.

    Uses only the locally known upstream; an identical-tree merge moves the ref alone.
    """
    from app.utils._git_core import fast_forward_same_tree

    branch = run_git(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if branch.returncode == 0 and fast_forward_same_tree(repo, branch.stdout.strip(), fetch=False) == "updated":
        result["followed_published_merge"] = True


def commit_git_revision(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = False,
    skip_checks: bool = False,
    paths: Sequence[str] = (),
    with_ack: str | None = None,
) -> dict[str, Any]:
    if push:
        raise CommitError(COMMIT_PUBLICATION_GUIDANCE)
    if not message.strip():
        raise CommitError("commit message is required")
    result: dict[str, Any] = {
        "repo": repo.name,
        "path": str(repo),
        "status": "SKIP",
        "pushed": False,
    }
    selected_paths = _normalize_paths(repo, paths) if paths else []
    has_changes = _selected_paths_dirty(repo, selected_paths) if selected_paths else dirty(repo)
    if not has_changes:
        return {**result, "reason": "no_changes_in_selected_paths" if selected_paths else "clean"}
    _follow_published_merge(repo, result)
    selected_files = _selected_changed_files(repo, selected_paths) if selected_paths and has_changes else []
    changed_scope = (selected_files if selected_paths else _selected_changed_files(repo, ["."])) if has_changes else []
    _require_foreign_leases_clear(repo, changed_scope)
    try:
        coord.guard(repo, "commit", with_ack=with_ack)
    except coord.CoordBlocked as exc:
        raise CommitError(str(exc)) from None
    scope = changed_scope
    if not skip_checks and (has_changes or scope):
        check_started = time.monotonic()
        for attempt in range(1, CHECK_ATTEMPTS + 1):
            before_checks = workspace_fingerprint(repo)
            before_files = _checkout_snapshot(repo) if selected_paths else None
            ok, detail = run_checks(repo, paths=scope, full=False)
            result["check_count"] = attempt
            if workspace_fingerprint(repo) == before_checks:
                break
            changed = _snapshot_changes(repo, before_files) if before_files is not None else set()
            outside_only = bool(changed) and not changed & set(scope)
            if outside_only and attempt < CHECK_ATTEMPTS:
                # Another session edited files outside this selection; the
                # selection itself is intact, so one fresh run is enough.
                continue
            result["check_duration_ms"] = round((time.monotonic() - check_started) * 1000, 3)
            return {
                **result,
                "status": "BLOCKED",
                "reason": "source_changed_during_checks",
                "detail": _changed_detail(changed, scope, retried=attempt > 1),
            }
        result["check_duration_ms"] = round((time.monotonic() - check_started) * 1000, 3)
        if not ok:
            return {**result, "status": "BLOCKED", "reason": "quality_gates_failed", "detail": detail}
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
    base = run_git(repo, ["rev-parse", "--verify", "HEAD"])
    base_sha = base.stdout.strip() if base.returncode == 0 else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    validated_patch = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--full-index", base_sha, "--", *changed_scope],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if validated_patch.returncode != 0:
        raise CommitError(
            validated_patch.stderr.decode(errors="replace").strip()
            or "cannot bind checkpoint checks to the staged candidate"
        )
    commit_args = ["commit", "-m", message]
    if selected_paths:
        commit_args.extend(["--only", "--", *selected_files])
    committed = (_commit_selected_index(repo, message, selected_files)
                 if selected_paths and len(addable) != len(selected_files)
                 else run_git(repo, commit_args))
    if committed.returncode != 0:
        raise CommitError(committed.stderr.strip() or committed.stdout.strip() or "git commit failed")
    sha = run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    committed_patch = subprocess.run(
        ["git", "diff", "--binary", "--full-index", base_sha, sha, "--", *changed_scope],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if committed_patch.returncode != 0 or committed_patch.stdout != validated_patch.stdout:
        raise CommitError(
            "commit created but its tree does not match the candidate that passed checkpoint checks"
        )
    result.update({"status": "SUCCESS", "sha": sha, "message": message})
    _release_committed_leases(repo, changed_scope)
    if selected_paths:
        result["selected_paths"] = selected_paths
    if task_id:
        result["task_id"] = task_id
    return result


def _refresh_symbols_after_publish(repo: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Queue a targeted symbol reindex of a successful local commit's files.

    Bridges the bi-hourly sweep gap so fresh symbols are searchable
    immediately. Best-effort: a completed commit must never fail on this.
    """
    if result.get("status") != "SUCCESS":
        return result
    sha = str(result.get("sha") or "").strip()
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


def _record_task_commit(repo: Path, result: dict[str, Any], *, task_id: str) -> dict[str, Any]:
    """Associate a successful local checkpoint with its task immediately."""
    if not task_id or result.get("status") != "SUCCESS":
        return result
    source = str(result.get("sha") or "").strip()
    if not source:
        raise CommitError("local task commit is missing its source identity")
    from app.storage.tasks import add_commit

    from .execution_context import resolve_checkout_project_id

    project_id = resolve_checkout_project_id(repo)
    if not project_id:
        raise CommitError("cannot correlate local commit with this checkout's project")
    try:
        stored = add_commit(task_id, source, project_id=project_id)
    except Exception as exc:
        raise CommitError("local revision could not be recorded on the task") from exc
    if stored is None:
        raise CommitError("local task commit does not belong to this checkout's project")
    return {**result, "task_commit": {"task_id": task_id, "source_commit": source}}


def commit_repo(
    repo: Path,
    *,
    message: str,
    task_id: str = "",
    push: bool = False,
    skip_checks: bool = False,
    paths: Sequence[str] = (),
    with_ack: str | None = None,
) -> dict[str, Any]:
    if push:
        raise CommitError(COMMIT_PUBLICATION_GUIDANCE)
    if task_id:
        try:
            renew_owned_claim(repo, task_id)
        except TaskClaimRenewalError as exc:
            raise CommitError(str(exc)) from exc
    try:
        with _commit_repo_lock(repo):
            result = commit_git_revision(
                repo,
                message=message,
                task_id=task_id,
                push=False,
                skip_checks=skip_checks,
                paths=paths,
                **({"with_ack": with_ack} if with_ack else {}),
            )
    except AcceptanceError as exc:
        raise CommitError(str(exc)) from exc
    result = _record_task_commit(repo, result, task_id=task_id)
    return _refresh_symbols_after_publish(repo, result)
