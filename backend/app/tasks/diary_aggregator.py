"""Celery task for aggregating session observations into diary entries.

Aggregates observations from Claude Code sessions into diary entries
for the reflection system to analyze.
"""

from __future__ import annotations

import os
from typing import Any

from celery import shared_task  # type: ignore[import-untyped]

from ..logging_config import get_logger
from ..services.memory import DiaryService
from ..storage import memory as memory_storage

logger = get_logger(__name__)

# Global memory system kill switch - checked before processing
MEMORY_SYSTEM_ENABLED = os.getenv("MEMORY_SYSTEM_ENABLED", "true").lower() in ("true", "1", "yes")

# Scheduled sessions waiting for aggregation (session_id -> scheduled_at)
_pending_sessions: dict[str, float] = {}


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.aggregate_session_diary",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def aggregate_session_diary(self: Any, project_id: str, session_id: str) -> dict[str, Any]:
    """Aggregate observations from a session into a diary entry.

    Called after session observations have been processed. Creates a diary
    entry summarizing what happened in the session.

    Args:
        project_id: Project ID
        session_id: Session ID to aggregate

    Returns:
        Summary dict with entry_id or skip reason
    """
    # Global kill switch - memory system disabled pending migration
    if not MEMORY_SYSTEM_ENABLED:
        logger.debug("diary_aggregation_skipped: memory system disabled")
        return {"status": "skipped", "reason": "memory_system_disabled"}

    logger.info(f"diary_aggregation_started: project={project_id}, session={session_id[:16]}...")

    # Check if diary entry already exists for this session (debounce)
    existing = memory_storage.get_diary_entry_by_session(project_id, session_id)
    if existing:
        logger.info(
            f"diary_aggregation_skipped: entry already exists for session {session_id[:16]}..."
        )
        return {"status": "skipped", "reason": "entry_exists", "entry_id": existing["id"]}

    # Get all observations for this session
    observations = memory_storage.get_observations_by_session(project_id, session_id)

    if not observations:
        logger.info(f"diary_aggregation_skipped: no observations for session {session_id[:16]}...")
        return {"status": "skipped", "reason": "no_observations"}

    # Aggregate metrics
    total_tokens = sum(obs.get("discovery_tokens", 0) or 0 for obs in observations)
    error_count = sum(1 for obs in observations if obs.get("observation_type") == "error")
    decision_count = sum(1 for obs in observations if obs.get("observation_type") == "decision")

    # Aggregate concepts from all observations
    all_concepts: set[str] = set()
    for obs in observations:
        concepts = obs.get("concepts") or []
        all_concepts.update(concepts)

    # Aggregate files modified
    files_modified: set[str] = set()
    for obs in observations:
        files = obs.get("files_modified") or []
        files_modified.update(files)

    # Determine outcome based on error rate
    if error_count == 0:
        outcome = "success"
    elif error_count < len(observations) / 2:
        outcome = "partial"
    else:
        outcome = "failure"

    # Aggregate what_worked and what_failed from observations
    what_worked = []
    what_failed = []
    for obs in observations:
        if obs.get("observation_type") == "error":
            # Extract title/narrative from error observations
            title = obs.get("title", "")
            if title:
                what_failed.append(title[:100])  # Truncate long titles
        elif obs.get("observation_type") in ("decision", "pattern"):
            title = obs.get("title", "")
            if title:
                what_worked.append(title[:100])

    # Limit to top 10 each
    what_worked = what_worked[:10]
    what_failed = what_failed[:10]

    # Create diary entry (returns None if memory disabled)
    diary_service = DiaryService(project_id)
    entry = diary_service.create_entry(
        session_id=session_id,
        agent_type="claude-code",
        outcome=outcome,
        discovery_tokens=total_tokens,
        concepts=list(all_concepts)[:20],  # Limit to 20 concepts
        what_worked=what_worked if what_worked else None,
        what_failed=what_failed if what_failed else None,
    )

    # Memory disabled at storage layer
    if entry is None:
        logger.info(f"diary_aggregation_skipped: memory disabled for {project_id}")
        return {"status": "skipped", "reason": "memory_disabled"}

    logger.info(
        f"diary_aggregation_completed: entry_id={entry['id']}, "
        f"observations={len(observations)}, outcome={outcome}, "
        f"errors={error_count}, decisions={decision_count}"
    )

    # Trigger reflection check after diary entry created
    from .reflection_processor import check_reflection_trigger

    try:
        check_reflection_trigger.delay(project_id=project_id)
        logger.debug(f"reflection_trigger_check_scheduled: project={project_id}")
    except Exception as e:
        # Don't fail diary aggregation for reflection trigger failures
        logger.warning(f"reflection_trigger_check_failed: {e}")

    return {
        "status": "created",
        "entry_id": entry["id"],
        "observations_count": len(observations),
        "outcome": outcome,
        "error_count": error_count,
        "decision_count": decision_count,
    }
