"""Snapshot data models and exception types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    """Manifest entry for a Btrfs-backed project snapshot."""

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

    capture_root: str | None = None
    project_relative_path: str = "."
    source_digest: str | None = None
    unfinished: bool | None = False  # None: captured saved-work state is unclassified.
    pin_reason: str | None = None
    pin_until: str | None = None
    recovery_active: bool = False
    deletion_error: str | None = None
    nested_subvolumes: list[str] = field(default_factory=list)
    shared_capture: bool = False
    recovery_copies: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuickSnapshot:
        scope_path = data.get("scope_path") or data.get("path")
        if not scope_path:
            raise KeyError("scope_path")
        copies = [dict(copy) for copy in data.get("recovery_copies") or []]
        for copy in copies:
            if not isinstance(copy.get("active"), bool) and not copy.get("deleted_at"):
                copy["active"] = True
                copy["released_at"] = None
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
            capture_root=data.get("capture_root"),
            project_relative_path=str(data.get("project_relative_path") or "."),
            source_digest=data.get("source_digest"),
            # Missing/null legacy evidence is unknown, never proof of clean work.
            unfinished=data["unfinished"] if isinstance(data.get("unfinished"), bool) else None,
            pin_reason=data.get("pin_reason"),
            pin_until=data.get("pin_until"),
            # Legacy writable side copies can contain unique saved edits. Only
            # an explicit boolean false establishes that the owner released one.
            recovery_active=(data["recovery_active"] if isinstance(data.get("recovery_active"), bool)
                else bool(data.get("recovery_path") or data.get("recovery_copies"))),
            deletion_error=data.get("deletion_error"),
            nested_subvolumes=list(data.get("nested_subvolumes") or []),
            shared_capture=bool(data.get("shared_capture", False)),
            recovery_copies=copies,
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
