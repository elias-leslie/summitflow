"""Git, Btrfs parsing, scope resolution, and snapshot lookup helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..repo_git import RepoGitError, get_repo_root
from ..workspace_paths import (
    get_lanes_base_dir,
    get_projects_base_dir,
    workspaces_root_available,
)
from ._models import QuickSnapshot, SnapshotError, SnapshotScope, SnapshotUsage


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "snapshot"


def _snapshot_id(name: str | None) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    if name:
        return f"{timestamp}-{_sanitize_label(name)[:40]}-{suffix}"
    return f"{timestamp}-{suffix}"


def _git(
    repo_root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Git command failed: git {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run git {' '.join(args)}: {exc}") from exc


def _parse_btrfs_du_raw(output: str, expected_path: Path) -> SnapshotUsage:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        raise SnapshotError(
            "Unable to parse snapshot usage output from btrfs filesystem du.\n"
            f"  path: {expected_path}"
        )

    raw_parts = lines[-1].split(maxsplit=3)
    if len(raw_parts) != 4:
        raise SnapshotError(
            "Unexpected btrfs filesystem du output format.\n"
            f"  path: {expected_path}\n"
            f"  line: {lines[-1]}"
        )

    total_raw, exclusive_raw, shared_raw, resolved_path = raw_parts
    if Path(resolved_path).resolve() != expected_path.resolve():
        raise SnapshotError(
            "Btrfs usage output did not match the requested snapshot path.\n"
            f"  expected: {expected_path}\n"
            f"  actual:   {resolved_path}"
        )

    return SnapshotUsage(
        total_bytes=int(total_raw),
        exclusive_bytes=int(exclusive_raw),
        shared_bytes=int(shared_raw),
    )


def _resolve_repo_root(cwd: str | Path | None = None) -> Path:
    try:
        return get_repo_root(Path(cwd) if cwd is not None else None)
    except RepoGitError as exc:
        raise SnapshotError(str(exc)) from exc


def _head_oid(repo_root: Path) -> str | None:
    result = _git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _head_ref(repo_root: Path) -> str | None:
    result = _git(repo_root, ["symbolic-ref", "-q", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _absolute_git_dir(repo_root: Path) -> Path:
    result = _git(repo_root, ["rev-parse", "--path-format=absolute", "--git-dir"])
    return Path(result.stdout.strip()).resolve()


def _absolute_git_common_dir(repo_root: Path) -> Path:
    result = _git(repo_root, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    return Path(result.stdout.strip()).resolve()


def _canonical_repo_root(repo_root: Path) -> Path:
    common_dir = _absolute_git_common_dir(repo_root)
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return common_dir.resolve()


def _require_workspaces() -> None:
    if not workspaces_root_available():
        raise SnapshotError(
            "Shared Btrfs workspaces are not available on this host. "
            "Mount /srv/workspaces first."
        )


def _resolve_scope(repo_root: Path, project_id: str) -> SnapshotScope:
    _require_workspaces()
    resolved_root = repo_root.resolve()

    project_path = get_projects_base_dir(project_id).resolve()
    if resolved_root == project_path:
        return SnapshotScope("project", project_id, resolved_root)

    lanes_base = get_lanes_base_dir(project_id).resolve()
    try:
        relative = resolved_root.relative_to(lanes_base)
    except ValueError as exc:
        raise SnapshotError(
            "Snapshots only work inside Btrfs-backed project roots or task lanes.\n"
            f"  current: {resolved_root}\n"
            f"  project: {project_path}\n"
            f"  lanes:   {lanes_base}"
        ) from exc

    if len(relative.parts) != 1:
        raise SnapshotError(
            "Expected the current lane to be a direct child of the Btrfs lanes root.\n"
            f"  current: {resolved_root}\n"
            f"  lanes:   {lanes_base}"
        )

    return SnapshotScope("lane", relative.parts[0], resolved_root)


def _find_snapshot(target: str, entries: list[QuickSnapshot]) -> QuickSnapshot:
    if not entries:
        raise SnapshotError("No snapshots found for the current scope.")

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

    raise SnapshotError(f"Snapshot '{target}' was not found for the current scope.")


def _safe_cwd_for_scope(scope_path: Path) -> Path:
    if scope_path.parent.name == "projects":
        candidate = scope_path.parent.parent
        return candidate if candidate.exists() else Path.home()
    if len(scope_path.parents) >= 3 and scope_path.parent.parent.name == "lanes":
        candidate = scope_path.parents[2]
        return candidate if candidate.exists() else Path.home()
    workspaces_root = Path(os.environ.get("ST_WORKSPACES_ROOT", "/srv/workspaces"))
    return workspaces_root if workspaces_root.exists() else Path.home()


def _restore_lane_git_state(repo_root: Path, snapshot: QuickSnapshot) -> None:
    if snapshot.head_oid is None:
        raise SnapshotError("Snapshot is missing the recorded HEAD commit.")

    git_dir = Path(snapshot.git_dir)
    head_file = git_dir / "HEAD"

    if snapshot.head_ref:
        _git(repo_root, ["update-ref", snapshot.head_ref, snapshot.head_oid])
        head_file.write_text(f"ref: {snapshot.head_ref}\n", encoding="utf-8")
    else:
        head_file.write_text(f"{snapshot.head_oid}\n", encoding="utf-8")

    if snapshot.index_artifact_path:
        artifact_path = Path(snapshot.index_artifact_path)
        if not artifact_path.exists():
            raise SnapshotError(f"Snapshot index artifact is missing: {artifact_path}")
        shutil.copy2(artifact_path, git_dir / "index")


def _resolve_lane_repo_root(lane_path: Path) -> Path:
    """Resolve the canonical repo root from a legacy lane checkout metadata file."""
    git_file = lane_path / ".git"
    if not git_file.is_file():
        raise SnapshotError(
            f"Expected legacy checkout metadata at {git_file}, but it was missing."
        )

    content = git_file.read_text(encoding="utf-8").strip()
    if not content.startswith("gitdir:"):
        raise SnapshotError(f"Unexpected git checkout metadata format in {git_file}.")

    gitdir = Path(content.split(":", 1)[1].strip())
    common_dir = gitdir.parent.parent  # shared git admin dir -> .git
    if common_dir.name != ".git":
        raise SnapshotError(
            f"Could not resolve canonical repo root for lane {lane_path}."
        )

    return common_dir.parent
