"""Snapshot data models and exception types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class SnapshotError(Exception):
    """Raised when a snapshot operation cannot complete safely."""


@dataclass(frozen=True)
class SnapshotScope:
    """Resolved Btrfs scope for the current checkout."""

    scope_type: str
    scope_name: str
    path: Path


@dataclass
class QuickSnapshot:
    """Manifest entry for a Btrfs-backed lane or project snapshot."""

    id: str
    name: str | None
    project_id: str
    repo_root: str
    scope_path: str
    scope_type: str
    scope_name: str
    snapshot_path: str
    branch: str | None
    head_oid: str | None
    head_ref: str | None
    git_dir: str
    index_artifact_path: str | None
    created_at: str
    backend: str = "btrfs"
    source: str = "manual"
    last_restored_at: str | None = None
    last_recovered_at: str | None = None
    recovery_path: str | None = None
    recovery_branch: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuickSnapshot:
        scope_path = data.get("scope_path") or data.get("path")
        if not scope_path:
            raise KeyError("scope_path")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]) if data.get("name") else None,
            project_id=str(data["project_id"]),
            repo_root=str(data["repo_root"]),
            scope_path=str(scope_path),
            scope_type=str(data["scope_type"]),
            scope_name=str(data["scope_name"]),
            snapshot_path=str(data["snapshot_path"]),
            branch=str(data["branch"]) if data.get("branch") else None,
            head_oid=str(data["head_oid"]) if data.get("head_oid") else None,
            head_ref=str(data["head_ref"]) if data.get("head_ref") else None,
            git_dir=str(data["git_dir"]),
            index_artifact_path=(
                str(data["index_artifact_path"]) if data.get("index_artifact_path") else None
            ),
            created_at=str(data["created_at"]),
            backend=str(data.get("backend") or "btrfs"),
            source=str(data.get("source") or "manual"),
            last_restored_at=(
                str(data["last_restored_at"]) if data.get("last_restored_at") else None
            ),
            last_recovered_at=(
                str(data["last_recovered_at"]) if data.get("last_recovered_at") else None
            ),
            recovery_path=str(data["recovery_path"]) if data.get("recovery_path") else None,
            recovery_branch=(
                str(data["recovery_branch"]) if data.get("recovery_branch") else None
            ),
        )


@dataclass(frozen=True)
class SnapshotUsage:
    """Btrfs usage statistics for a single snapshot subvolume."""

    total_bytes: int
    exclusive_bytes: int
    shared_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total_bytes": self.total_bytes,
            "exclusive_bytes": self.exclusive_bytes,
            "shared_bytes": self.shared_bytes,
        }


@dataclass(frozen=True)
class LaneInspection:
    """Result of inspecting a Btrfs lane for cleanup."""

    project_id: str
    lane_name: str
    lane_path: Path
    has_checkout_metadata: bool
    branch: str | None
    snapshot_paths: list[Path]
    snapshot_dir: Path | None
    manifest_dir: Path | None

    @property
    def total_items(self) -> int:
        """Number of subvolumes that will be deleted (snapshots + lane)."""
        return len(self.snapshot_paths) + 1
