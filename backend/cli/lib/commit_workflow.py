"""Canonical st commit workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import coord, leases
from .acceptance import AcceptanceError, repo_lock, workspace_fingerprint
from .task_claims import TaskClaimRenewalError, renew_owned_claim


class CommitError(RuntimeError):
    """Raised when commit workflow cannot run."""


# Concurrent sessions share one repository mutation lock; a commit waits for
# another session's commit/acceptance (whose checks run inside the lock)
# instead of failing immediately, printing a progress line while it waits.
REPO_LOCK_WAIT_SECONDS = 300.0
REPO_LOCK_POLL_SECONDS = 2.0
REPO_LOCK_PROGRESS_SECONDS = 30.0
# Checks rerun once when only files outside a --paths selection changed.
CHECK_ATTEMPTS = 2

COMMIT_PUBLICATION_GUIDANCE = (
    "st commit creates local checkpoints; publish an accepted source explicitly with "
    "st vcs publish --source ID --sha FULL_OID --now"
)


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def _pathspecs(repo: Path, paths: Sequence[str]) -> list[str]:
    """Match an existing path such as a Next.js ``[id]`` route literally, not as a glob."""
    def literal(path: str) -> bool:
        if not any(char in path for char in "*?[") or path.startswith(":"):
            return False
        return (repo / path).exists() or run_git(
            repo, ["ls-files", "--error-unmatch", "--", f":(literal){path}"]).returncode == 0
    return [f":(literal){path}" if literal(path) else path for path in paths]


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
    result = run_git(repo, ["status", "--porcelain", "--", *_pathspecs(repo, paths)])
    if result.returncode != 0:
        raise CommitError(result.stderr.strip() or "cannot inspect selected working tree status")
    return bool(result.stdout.strip())


def _selected_changed_files(repo: Path, paths: Sequence[str]) -> list[str]:
    """Expand selected directories before passing the canonical gate its scope."""
    files: set[str] = set()
    head = run_git(repo, ["rev-parse", "--verify", "HEAD"])
    specs = _pathspecs(repo, paths)
    tracked = (["diff", "--name-only", "-z", "HEAD", "--", *specs] if head.returncode == 0
               else ["ls-files", "--cached", "-z", "--", *specs])
    for args in (
        tracked,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *specs],
    ):
        result = run_git(repo, args)
        if result.returncode != 0:
            raise CommitError(result.stderr.strip() or "cannot resolve selected check paths")
        files.update(item for item in result.stdout.split("\0") if item)
    return sorted(files) or list(paths)


def _build_output_directories() -> frozenset[str]:
    from cli.tool_registry import load_tool_registry

    names = load_tool_registry().get("checkpoint_build_output", {}).get("directories", [])
    return frozenset(name for name in names if isinstance(name, str))


def _drop_untracked_build_output(
    repo: Path, selected: Sequence[str], files: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Split off build-output directories the checkpoint was not told to take.

    Without a .gitignore, `node_modules/` or `dist/` looks like new source and a
    whole-tree or directory checkpoint would commit it. Returns (kept files,
    skipped directories). A directory with any tracked file stays, and so does
    one a selected path reaches into to name.
    """
    directories = _build_output_directories()
    named = [Path(os.path.normpath(path)).parts for path in selected]
    prefix_of: dict[str, str] = {}
    for path in files:
        parts = Path(path).parts
        for index, part in enumerate(parts[:-1]):
            if part in directories and not any(
                len(item) > index and item[: index + 1] == parts[: index + 1] for item in named
            ):
                prefix_of[path] = "/".join(parts[: index + 1])
                break
    if not prefix_of:
        return list(files), []
    prefixes = sorted(set(prefix_of.values()))
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--", *(f":(literal){prefix}" for prefix in prefixes)],
        cwd=repo, capture_output=True, check=False,
    )
    if listed.returncode != 0:
        return list(files), []
    tracked = [item for item in listed.stdout.decode(errors="surrogateescape").split("\0") if item]
    skipped = [prefix for prefix in prefixes if not any(item.startswith(prefix + "/") for item in tracked)]
    kept = [path for path in files if prefix_of.get(path) not in skipped]
    return kept, skipped


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
    started = time.monotonic()
    deadline = started + REPO_LOCK_WAIT_SECONDS
    noticed = False
    next_progress = started + REPO_LOCK_PROGRESS_SECONDS
    while True:
        stack = ExitStack()
        try:
            stack.enter_context(repo_lock(repo, purpose="commit"))
        except AcceptanceError as exc:
            now = time.monotonic()
            if not str(exc).startswith("repo_mutation_in_progress") or now >= deadline:
                raise
            if not noticed:
                print(f"st commit: another repository operation is running; waiting up to "
                      f"{REPO_LOCK_WAIT_SECONDS:.0f}s for it to finish", file=sys.stderr)
                noticed = True
            elif now >= next_progress:
                print(f"st commit: still waiting for the repository lock "
                      f"({now - started:.0f}s of {REPO_LOCK_WAIT_SECONDS:.0f}s)", file=sys.stderr)
                next_progress = now + REPO_LOCK_PROGRESS_SECONDS
            time.sleep(REPO_LOCK_POLL_SECONDS)
            continue
        with stack:
            yield
        return


def _require_no_sweep(repo: Path, selected: Sequence[str], changed: Sequence[str]) -> None:
    """Refuse to absorb another session's dirty work into this checkpoint.

    A whole-tree or directory scope is refused when any dirty path in it has a
    writer from another session or an unknown writer; an explicitly named file
    is refused only when another session wrote it.
    """
    resolved = coord.project_for_path(repo)
    if resolved is None or not changed:
        return
    project_id, root = resolved
    foreign = coord.foreign_writers(project_id, root, changed)
    if not foreign:
        return
    # A changed file not named exactly came in through the whole tree, a directory or a glob.
    explicit = {os.path.normpath(path) for path in selected} - {"."}
    swept: list[str] = []
    contested: list[str] = []
    for path, writers in sorted(foreign.items()):
        labels = ",".join(sorted({leases.writer_label(entry) for entry in writers}))
        if path not in explicit:
            swept.append(f"{path}<-{labels}")
        elif any(entry.get("agent_id") != leases.UNKNOWN_WRITER for entry in writers):
            contested.append(f"{path}<-{labels}")

    def listed(items: list[str]) -> str:
        return ", ".join(items[:5]) + (f" (+{len(items) - 5} more)" if len(items) > 5 else "")

    reasons = []
    if swept:
        reasons.append(f"this scope would sweep in work written by another session or an unknown writer: {listed(swept)}; "
                       "commit only your own files with explicit paths: st commit -m ... --paths <file> <file>")
    if contested:
        reasons.append(f"another session also wrote {listed(contested)}; leave it to them, or once agreed adopt it "
                       "with st lease --take <path>")
    if not reasons:
        return
    _log_sweep_refusal(project_id, swept + contested)
    raise CommitError("; ".join(reasons))


def _log_sweep_refusal(project_id: str, items: Sequence[str]) -> None:
    """Append one line per refusal so the guard's false-positive rate can be reviewed."""
    with suppress(OSError):
        leases.LEASES_DIR.mkdir(parents=True, exist_ok=True)
        with (leases.LEASES_DIR / "_sweep_refusals.jsonl").open("a") as handle:
            handle.write(json.dumps({"at": datetime.now(UTC).isoformat(), "project": project_id,
                                     "agent": leases.identify_agent()[0], "paths": list(items)[:20]}) + "\n")


def _release_committed_leases(repo: Path, committed: Sequence[str]) -> None:
    """Committed work is no longer in flight: drop the committer's file leases and clean paths' writer sets."""
    resolved = coord.project_for_path(repo)
    if resolved is None or not committed:
        return
    with suppress(OSError):
        leases.release_paths(resolved[0], [str(resolved[1] / path) for path in committed])
    remaining = coord.dirty_paths(resolved[1])
    if remaining is not None:
        with suppress(OSError):
            root = resolved[1].resolve()
            leases.prune_writers(resolved[0], str(root), {str(root / rel) for rel in remaining})


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
                and run_git(repo, ["ls-files", "--error-unmatch", "--", *_pathspecs(repo, [path])]).returncode != 0):
            continue
        addable.append(path)
    return addable


def _commit_selected_index(repo: Path, message: str, paths: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Commit staged selections without rescanning ignored worktree replacements."""
    patch = subprocess.run(["git", "diff", "--cached", "--binary", "--full-index", "--", *_pathspecs(repo, paths)],
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
            reconciled = run_git(repo, ["reset", "--quiet", "HEAD", "--", *_pathspecs(repo, paths)])
            if reconciled.returncode != 0:
                raise CommitError(reconciled.stderr.strip() or "commit created; selected index reconciliation failed")
        return committed


def _run_checkpoint_checks(
    repo: Path, scope: list[str], selected: bool, result: dict[str, Any]
) -> dict[str, Any] | None:
    """Run the quick gate on ``scope``, recording its fields in ``result``.

    Returns the BLOCKED result when the gate fails or the checkout changed while
    it ran, else ``None``.
    """
    check_started = time.monotonic()
    for attempt in range(1, CHECK_ATTEMPTS + 1):
        before_checks = workspace_fingerprint(repo)
        before_files = _checkout_snapshot(repo) if selected else None
        ok, detail = run_checks(repo, paths=scope, full=False)
        result["check_count"] = attempt
        if "CHECK:REUSED:quick" in detail:
            result["check_reused"] = True
        else:
            result.pop("check_reused", None)
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
    return None


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
    changed_scope, skipped_dirs = _drop_untracked_build_output(
        repo, selected_paths, _selected_changed_files(repo, selected_paths or ["."]))
    selected_files = changed_scope if selected_paths else []
    if skipped_dirs:
        result["skipped_untracked"] = skipped_dirs
        if not changed_scope:
            return {**result, "reason": "only_untracked_build_output"}
    _require_no_sweep(repo, selected_paths, changed_scope)
    try:
        coord.guard(repo, "commit", with_ack=with_ack)
    except coord.CoordBlocked as exc:
        raise CommitError(str(exc)) from None
    if not skip_checks and (blocked := _run_checkpoint_checks(repo, changed_scope, bool(selected_paths), result)):
        return blocked
    if selected_paths:
        addable = _addable_paths(repo, selected_files)
        if addable:
            add = run_git(repo, ["add", "--", *_pathspecs(repo, addable)])
            if add.returncode != 0:
                raise CommitError(add.stderr.strip() or "git add failed")
    else:
        add = run_git(repo, ["add", "-A", "--", ".", *(f":(exclude,literal){item}" for item in skipped_dirs)])
        if add.returncode != 0:
            raise CommitError(add.stderr.strip() or "git add failed")
    if run_git(repo, ["diff", "--cached", "--quiet"]).returncode == 0:
        return {**result, "reason": "no_staged_changes"}
    base = run_git(repo, ["rev-parse", "--verify", "HEAD"])
    base_sha = base.stdout.strip() if base.returncode == 0 else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    validated_patch = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--full-index", base_sha, "--", *_pathspecs(repo, changed_scope)],
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
        commit_args.extend(["--only", "--", *_pathspecs(repo, selected_files)])
    committed = (_commit_selected_index(repo, message, selected_files)
                 if selected_paths and len(addable) != len(selected_files)
                 else run_git(repo, commit_args))
    if committed.returncode != 0:
        raise CommitError(committed.stderr.strip() or committed.stdout.strip() or "git commit failed")
    sha = run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    committed_patch = subprocess.run(
        ["git", "diff", "--binary", "--full-index", base_sha, sha, "--", *_pathspecs(repo, changed_scope)],
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
    return _record_task_commit(repo, result, task_id=task_id)
