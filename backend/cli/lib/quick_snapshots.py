"""Fast per-worktree snapshots backed by hidden Git refs.

These snapshots are intentionally scoped to the current worktree lane. They
capture the Git HEAD, the staged index state, and the current worktree tree
(tracked + untracked, excluding ignored files). Ignored files are left
untouched on restore so shared dependency directories like node_modules do not
get deleted out from under sibling worktrees.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .worktree_git import WorktreeError, get_current_branch, get_repo_root


class SnapshotError(Exception):
    """Raised when a snapshot operation cannot complete safely."""


@dataclass
class QuickSnapshot:
    """Manifest entry for a quick per-worktree snapshot."""

    id: str
    name: str | None
    project_id: str
    repo_root: str
    worktree_path: str
    git_ref: str
    commit_oid: str
    head_oid: str | None
    index_tree: str
    worktree_tree: str
    branch: str | None
    created_at: str
    backend: str = "git-ref"
    jj_operation_id: str | None = None
    btrfs_snapshot_path: str | None = None
    last_restored_at: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuickSnapshot:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]) if data.get("name") else None,
            project_id=str(data["project_id"]),
            repo_root=str(data["repo_root"]),
            worktree_path=str(data["worktree_path"]),
            git_ref=str(data["git_ref"]),
            commit_oid=str(data["commit_oid"]),
            head_oid=str(data["head_oid"]) if data.get("head_oid") else None,
            index_tree=str(data["index_tree"]),
            worktree_tree=str(data["worktree_tree"]),
            branch=str(data["branch"]) if data.get("branch") else None,
            created_at=str(data["created_at"]),
            backend=str(data.get("backend") or "git-ref"),
            jj_operation_id=str(data["jj_operation_id"]) if data.get("jj_operation_id") else None,
            btrfs_snapshot_path=str(data["btrfs_snapshot_path"]) if data.get("btrfs_snapshot_path") else None,
            last_restored_at=str(data["last_restored_at"]) if data.get("last_restored_at") else None,
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "snapshot"


def _git(
    repo_root: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            input=input_text,
            env=merged_env,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Git command failed: git {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run git {' '.join(args)}: {exc}") from exc


def _resolve_repo_root(cwd: str | Path | None = None) -> Path:
    try:
        return get_repo_root(Path(cwd) if cwd is not None else None)
    except WorktreeError as exc:
        raise SnapshotError(str(exc)) from exc


def _head_oid(repo_root: Path) -> str | None:
    result = _git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _current_index_tree(repo_root: Path) -> str:
    return _git(repo_root, ["write-tree"]).stdout.strip()


def _current_worktree_tree(repo_root: Path, head_oid: str | None) -> str:
    with tempfile.NamedTemporaryFile(prefix="st-snap-index-", delete=False) as tmp_index:
        temp_index_path = tmp_index.name
    try:
        env = {"GIT_INDEX_FILE": temp_index_path}
        if head_oid:
            _git(repo_root, ["read-tree", head_oid], env=env)
        _git(repo_root, ["add", "-A"], env=env)
        return _git(repo_root, ["write-tree"], env=env).stdout.strip()
    finally:
        Path(temp_index_path).unlink(missing_ok=True)


def _scope_key(worktree_path: Path) -> str:
    basename = _sanitize_label(worktree_path.name)
    digest = hashlib.sha1(str(worktree_path).encode("utf-8")).hexdigest()[:10]
    return f"{basename}-{digest}"


def _manifest_dir(project_id: str, worktree_path: Path) -> Path:
    target = Path.home() / ".local" / "share" / "st" / "snaps" / project_id / _scope_key(worktree_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _manifest_path(project_id: str, worktree_path: Path) -> Path:
    return _manifest_dir(project_id, worktree_path) / "manifest.json"


def _load_manifest(project_id: str, worktree_path: Path) -> list[QuickSnapshot]:
    path = _manifest_path(project_id, worktree_path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"Snapshot manifest is invalid: {path}") from exc
    if not isinstance(raw, list):
        raise SnapshotError(f"Snapshot manifest has unexpected format: {path}")
    entries = [QuickSnapshot.from_dict(item) for item in raw if isinstance(item, dict)]
    entries.sort(key=lambda entry: entry.created_at, reverse=True)
    return entries


def _save_manifest(project_id: str, worktree_path: Path, entries: list[QuickSnapshot]) -> None:
    path = _manifest_path(project_id, worktree_path)
    ordered = sorted(entries, key=lambda entry: entry.created_at, reverse=True)
    path.write_text(
        json.dumps([entry.to_dict() for entry in ordered], indent=2),
        encoding="utf-8",
    )


def _snapshot_id(name: str | None) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    if name:
        return f"{timestamp}-{_sanitize_label(name)[:40]}-{suffix}"
    return f"{timestamp}-{suffix}"


def _create_snapshot_commit(repo_root: Path, snapshot: QuickSnapshot) -> str:
    args = ["commit-tree", snapshot.worktree_tree]
    if snapshot.head_oid:
        args.extend(["-p", snapshot.head_oid])
    message_lines = [
        "st quick snapshot",
        "",
        f"snapshot-id: {snapshot.id}",
        f"project-id: {snapshot.project_id}",
        f"name: {snapshot.name or ''}",
        f"worktree-path: {snapshot.worktree_path}",
        f"head: {snapshot.head_oid or ''}",
        f"index-tree: {snapshot.index_tree}",
        f"worktree-tree: {snapshot.worktree_tree}",
        f"branch: {snapshot.branch or ''}",
        f"created-at: {snapshot.created_at}",
        "backend: git-ref",
    ]
    return _git(repo_root, args, input_text="\n".join(message_lines)).stdout.strip()


def _find_snapshot(target: str, entries: list[QuickSnapshot]) -> QuickSnapshot:
    if not entries:
        raise SnapshotError("No snapshots found for the current worktree.")

    if re.fullmatch(r"-\d+", target):
        idx = abs(int(target)) - 1
        if idx >= len(entries):
            raise SnapshotError(f"Snapshot index {target} is out of range.")
        return entries[idx]

    exact_id = next((entry for entry in entries if entry.id == target), None)
    if exact_id:
        return exact_id

    named = next((entry for entry in entries if entry.name == target), None)
    if named:
        return named

    prefix = next((entry for entry in entries if entry.id.startswith(target)), None)
    if prefix:
        return prefix

    raise SnapshotError(f"Snapshot '{target}' was not found for the current worktree.")


def capture_snapshot(
    name: str | None,
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    worktree_path = repo_root
    entries = _load_manifest(project_id, worktree_path)

    head_oid = _head_oid(repo_root)
    if head_oid is None:
        raise SnapshotError("Quick snapshots require a repository with at least one commit.")

    created_at = _now_iso()
    snapshot = QuickSnapshot(
        id=_snapshot_id(name),
        name=name or None,
        project_id=project_id,
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        git_ref=f"refs/st-snapshots/{_scope_key(worktree_path)}/{_snapshot_id(name)}",
        commit_oid="",
        head_oid=head_oid,
        index_tree=_current_index_tree(repo_root),
        worktree_tree=_current_worktree_tree(repo_root, head_oid),
        branch=get_current_branch(repo_root),
        created_at=created_at,
    )
    snapshot.git_ref = f"refs/st-snapshots/{_scope_key(worktree_path)}/{snapshot.id}"
    snapshot.commit_oid = _create_snapshot_commit(repo_root, snapshot)
    _git(repo_root, ["update-ref", snapshot.git_ref, snapshot.commit_oid])

    entries.append(snapshot)
    _save_manifest(project_id, worktree_path, entries)
    return snapshot


def list_snapshots(
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> list[QuickSnapshot]:
    repo_root = _resolve_repo_root(cwd)
    return _load_manifest(project_id, repo_root)


def restore_snapshot(
    target: str,
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    entries = _load_manifest(project_id, repo_root)
    snapshot = _find_snapshot(target, entries)

    current_worktree = str(repo_root)
    if snapshot.worktree_path != current_worktree:
        raise SnapshotError(
            "Snapshot belongs to a different worktree lane.\n"
            f"  snapshot: {snapshot.worktree_path}\n"
            f"  current:  {current_worktree}"
        )

    current_branch = get_current_branch(repo_root)
    if snapshot.branch and current_branch and snapshot.branch != current_branch:
        raise SnapshotError(
            f"Snapshot belongs to branch '{snapshot.branch}', but current branch is '{current_branch}'."
        )

    if snapshot.head_oid is None:
        raise SnapshotError("Snapshot is missing the recorded HEAD commit.")

    _git(repo_root, ["reset", "--hard", snapshot.head_oid])
    _git(repo_root, ["clean", "-fd"])
    _git(repo_root, ["read-tree", "--reset", "-u", snapshot.worktree_tree])
    _git(repo_root, ["read-tree", "--reset", snapshot.index_tree])

    updated_entries: list[QuickSnapshot] = []
    restored_at = _now_iso()
    for entry in entries:
        if entry.id == snapshot.id:
            entry = QuickSnapshot.from_dict(
                {
                    **entry.to_dict(),
                    "last_restored_at": restored_at,
                }
            )
            snapshot = entry
        updated_entries.append(entry)
    _save_manifest(project_id, repo_root, updated_entries)
    return snapshot


__all__ = [
    "QuickSnapshot",
    "SnapshotError",
    "capture_snapshot",
    "list_snapshots",
    "restore_snapshot",
]
