"""Memory Backfill API - Mine session history for patterns.

Endpoints:
- POST /memory/backfill - Mine session history for patterns
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from ..storage import memory as memory_storage
from .memory_models import BackfillRequest, BackfillResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_patterns_json(content: str, session_id: str, errors: list[str]) -> list[dict[str, Any]]:
    """Parse JSON array from LLM response."""
    import json
    import re

    try:
        if content.startswith("["):
            result = json.loads(content)
            return result if isinstance(result, list) else []
        # Try to extract JSON array from response
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            result = json.loads(match.group(0))
            return result if isinstance(result, list) else []
        return []
    except json.JSONDecodeError:
        errors.append(f"Session {session_id}: Failed to parse extraction result")
        return []


async def _run_backfill_async(
    project_id: str,
    sessions_limit: int,
    dry_run: bool,
) -> BackfillResponse:
    """Run the backfill operation.

    This function:
    1. Parses session history files
    2. Extracts patterns using HISTORY_EXTRACTION_PROMPT
    3. Stores patterns (if not dry_run)
    4. Returns summary
    """
    from ..services.memory.history_parser import HistoryParser
    from ..services.memory.observation_extractor import (
        HISTORY_EXTRACTION_PROMPT,
        ObservationExtractor,
    )

    parser = HistoryParser()
    extractor = ObservationExtractor()
    errors: list[str] = []
    patterns_extracted = 0
    observations_created = 0

    # Get session stats first
    stats = parser.get_session_stats(project_id)
    if not stats.get("exists"):
        return BackfillResponse(
            project_id=project_id,
            sessions_found=0,
            sessions_processed=0,
            patterns_extracted=0,
            observations_created=0,
            dry_run=dry_run,
            errors=[f"Project directory not found: {stats.get('project_dir')}"],
            session_stats=stats,
        )

    # List sessions (most recent first)
    session_paths = parser.list_sessions(project_id, limit=sessions_limit)

    if not session_paths:
        return BackfillResponse(
            project_id=project_id,
            sessions_found=0,
            sessions_processed=0,
            patterns_extracted=0,
            observations_created=0,
            dry_run=dry_run,
            errors=["No session files found"],
            session_stats=stats,
        )

    sessions_processed = 0

    for session_path in session_paths:
        try:
            session = parser.parse_session_file(session_path)

            # Skip sessions with no meaningful content
            if not session.tool_calls and not session.user_corrections:
                continue

            # Build excerpt for extraction
            excerpt_parts = []

            # Add failed commands
            for fc in session.failed_commands[:5]:  # Limit to avoid context overflow
                excerpt_parts.append(
                    f"FAILED COMMAND:\n  Tool: {fc.tool_name}\n  Error: {fc.error_message or 'unknown'}"
                )

            # Add user corrections
            for uc in session.user_corrections[:5]:
                excerpt_parts.append(f"USER CORRECTION:\n  {uc.content[:500]}")

            # Add some successful recoveries (tool calls after failures)
            # Simple heuristic: if there's a failed command followed by similar tool call that succeeded
            if session.failed_commands and len(session.tool_calls) > len(session.failed_commands):
                excerpt_parts.append(
                    "RECOVERY: Session had failures followed by successful operations"
                )

            if not excerpt_parts:
                continue

            session_excerpt = "\n\n".join(excerpt_parts)

            if dry_run:
                # Just count what we'd process
                patterns_extracted += len(excerpt_parts)
                sessions_processed += 1
                logger.info(
                    f"[DRY RUN] Session {session.session_id}: "
                    f"would extract from {len(excerpt_parts)} items"
                )
            else:
                # Actually run extraction
                prompt = HISTORY_EXTRACTION_PROMPT.format(session_excerpt=session_excerpt)

                # Use the extractor's client for LLM call
                client = extractor._get_client()
                response = client.generate(prompt=prompt)

                # Parse response
                content = response.content.strip()
                patterns_data = _parse_patterns_json(content, session.session_id, errors)

                # Store patterns
                for pattern_data in patterns_data:
                    if not isinstance(pattern_data, dict):
                        continue

                    # Create observation from pattern
                    try:
                        obs = memory_storage.create_observation(
                            project_id=project_id,
                            session_id=session.session_id,
                            agent_type="backfill",
                            observation_type=pattern_data.get("observation_type", "operational"),
                            title=pattern_data.get("title", "Extracted pattern"),
                            narrative=pattern_data.get("narrative"),
                            confidence=pattern_data.get("confidence", 0.7),
                            concepts=["backfill"],
                            facts=pattern_data.get("facts"),
                            entities=pattern_data.get("entities"),
                            skip_memory_check=True,  # Backfill bypasses memory feature check
                        )
                        if obs:
                            observations_created += 1
                            patterns_extracted += 1
                    except Exception as e:
                        errors.append(f"Session {session.session_id}: Failed to store pattern: {e}")

                sessions_processed += 1

        except Exception as e:
            errors.append(f"Session {session_path.stem}: {e!s}")
            continue

    return BackfillResponse(
        project_id=project_id,
        sessions_found=len(session_paths),
        sessions_processed=sessions_processed,
        patterns_extracted=patterns_extracted,
        observations_created=observations_created,
        dry_run=dry_run,
        errors=errors[:20],  # Limit errors
        session_stats=stats,
    )


@router.post("/memory/backfill", response_model=BackfillResponse)
async def run_memory_backfill(
    request: BackfillRequest,
    background_tasks: BackgroundTasks,
) -> BackfillResponse:
    """Mine session history for patterns.

    This endpoint parses Claude session JSONL files from ~/.claude/projects/
    and extracts operational patterns like:
    - Failed commands and what to do instead
    - User corrections and preferences
    - Successful recoveries after failures

    Args:
        request: Backfill request with project_id, sessions_limit, dry_run

    Returns:
        BackfillResponse with counts and any errors
    """
    _ = background_tasks  # Reserved for future async processing
    logger.info(
        f"Starting backfill: project={request.project_id}, "
        f"limit={request.sessions_limit}, dry_run={request.dry_run}"
    )

    # Run synchronously for now (could be made async/background for large runs)
    result = await _run_backfill_async(
        project_id=request.project_id,
        sessions_limit=request.sessions_limit,
        dry_run=request.dry_run,
    )

    logger.info(
        f"Backfill complete: sessions={result.sessions_processed}, "
        f"patterns={result.patterns_extracted}, errors={len(result.errors)}"
    )

    return result
