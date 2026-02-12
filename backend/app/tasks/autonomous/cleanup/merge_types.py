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


class MergeBlocked(TypedDict):
    """Blocked merge result."""

    task_id: str
    status: Literal["blocked"]
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


MergeResult = (
    MergeSuccess | MergeBlocked | MergeSkipped | MergeRolledBack | MergeError
)
