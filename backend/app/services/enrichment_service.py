"""Backward compatibility module for enrichment_service.

This module re-exports all public APIs from the refactored enrichment_service
package to maintain backward compatibility.
"""

from __future__ import annotations

from .enrichment_service import (
    AcceptanceCriterion,
    DiscussionResponse,
    EnrichedTask,
    Subtask,
    ValidationResult,
    apply_discussion_changes,
    apply_enrichment_to_task,
    discuss_task,
    enrich_and_validate,
    enrich_task,
    validate_enrichment,
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
