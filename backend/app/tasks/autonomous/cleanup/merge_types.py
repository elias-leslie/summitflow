"""Type definitions for merge operations."""

from __future__ import annotations

from typing import Literal, TypedDict


class MergeSuccess(TypedDict):
    """Successful merge result."""

    task_id: str
    status: Literal["merged"]
    task_branch: str
    base_branch: str
    branch_deleted: bool
    post_merge_valid: bool
    post_merge_validation_status: Literal["passed", "failed", "timed_out", "skipped", "error"]


class MergeBlocked(TypedDict):
    """Blocked merge result."""

    task_id: str
    status: Literal["blocked"]
    reason: str


class MergeFailed(TypedDict):
    """Generic failed merge result without conflict details."""

    task_id: str
    status: Literal["failed"]
    reason: str


class MergeSkipped(TypedDict):
    """Skipped merge result."""

    task_id: str
    status: Literal["skipped"]
    reason: str


class MergeRolledBack(TypedDict):
    """Rolled back merge result."""

    task_id: str
    status: Literal["rolled_back"]
    task_branch: str
    base_branch: str
    reason: str


class MergeError(TypedDict):
    """Error during merge."""

    task_id: str
    status: Literal["error"]
    error: str


class MergeConflicted(TypedDict):
    """Merge conflict detected — task branch preserved for retry."""

    task_id: str
    status: Literal["failed"]
    task_branch: str
    base_branch: str
    conflicting_files: list[str]
    error_output: str


MergeResult = (
    MergeSuccess
    | MergeBlocked
    | MergeFailed
    | MergeSkipped
    | MergeRolledBack
    | MergeError
    | MergeConflicted
)
