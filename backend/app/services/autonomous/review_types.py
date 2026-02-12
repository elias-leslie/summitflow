"""Type definitions for review services.

Provides structured types for tasks, reviews, and related data structures.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Verdict = Literal["APPROVE", "REJECT", "REQUEST_FIX"]


class DiffStats(TypedDict):
    """Statistics about a git diff."""

    files_changed: int
    insertions: int
    deletions: int


class ReviewResult(TypedDict):
    """Result of a code review."""

    verdict: Verdict
    summary: str
    issues: list[str]
    suggestions: list[str]
    confidence: float
    diff_stats: NotRequired[DiffStats]
    reviewed_at: NotRequired[str]
    raw_response: NotRequired[str]


class Task(TypedDict, total=False):
    """Task data structure.

    Note: total=False makes all fields optional by default.
    """

    id: str
    title: str
    description: str
    project_id: str
    pre_merge_sha: str
    status: str
    labels: list[str]
    review_result: ReviewResult
    complexity: str


__all__ = [
    "DiffStats",
    "ReviewResult",
    "Task",
    "Verdict",
]
