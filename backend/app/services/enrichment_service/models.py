"""Data models for enrichment service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Subtask:
    """A single implementation subtask."""

    subtask_id: str
    phase: str
    description: str
    steps: list[str] = field(default_factory=list)


@dataclass
class EnrichedTask:
    """Result of task enrichment."""

    title: str
    objective: str
    description: str
    task_type: str
    priority: int
    labels: list[str]
    done_when: list[str]
    subtasks: list[Subtask]
    raw_json: dict[str, Any]
    validation_notes: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of enrichment validation."""

    valid: bool
    criteria_feedback: list[dict[str, Any]]
    missing_coverage: list[str]
    overall_notes: str


@dataclass
class DiscussionResponse:
    """Response from a task discussion."""

    response: str
    changes_made: list[str]
    updated_task: dict[str, Any] | None


__all__ = [
    "DiscussionResponse",
    "EnrichedTask",
    "Subtask",
    "ValidationResult",
]
