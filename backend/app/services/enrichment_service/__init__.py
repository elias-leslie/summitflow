"""Enrichment Service - AI-powered task enrichment using Opus and Gemini.

This service transforms raw user requests into structured tasks with
objectives, acceptance criteria, and implementation subtasks.

This module is organized as follows:
- models.py: Data models (AcceptanceCriterion, Subtask, EnrichedTask, etc.)
- parsers.py: Prompt loading and response parsing
- discussion.py: Task discussion functionality
- _core.py: enrich_task, validate_enrichment, enrich_and_validate
- _storage.py: apply_enrichment_to_task
"""

from ._core import enrich_and_validate, enrich_task, validate_enrichment
from ._storage import apply_enrichment_to_task
from .discussion import apply_discussion_changes, discuss_task
from .models import (
    AcceptanceCriterion,
    DiscussionResponse,
    EnrichedTask,
    Subtask,
    ValidationResult,
)

__all__ = [
    "AcceptanceCriterion",
    "DiscussionResponse",
    "EnrichedTask",
    "Subtask",
    "ValidationResult",
    "apply_discussion_changes",
    "apply_enrichment_to_task",
    "discuss_task",
    "enrich_and_validate",
    "enrich_task",
    "validate_enrichment",
]
