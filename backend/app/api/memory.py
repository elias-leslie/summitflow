"""Memory API - Memory system statistics, health, and global queries.

This module provides REST API endpoints for memory system monitoring:
- GET /api/memory/stats - System-wide memory statistics
- GET /api/observations - Global observations (all projects)
- GET /api/patterns - Global patterns (all projects)
- POST /api/memory/backfill - Mine session history for patterns
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel

from ..api.hooks import get_filtering_metrics
from ..storage import memory as memory_storage
from ..storage.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()


class FilteringMetrics(BaseModel):
    """Tool filtering metrics."""

    tools_received: int
    tools_queued: int
    tools_skipped: int
    skip_reasons: dict[str, int]
    filter_effectiveness: float  # Percentage of tools filtered


class LifecycleStats(BaseModel):
    """Lifecycle health metrics for memory system."""

    failed_queue_count: int  # Queue items in failed status
    stuck_queue_count: int  # Queue items stuck in processing > 1 hour
    oldest_pending_age_minutes: int | None  # Age of oldest pending queue item
    unreflected_diary_count: int  # Diary entries never reflected
    stale_patterns_count: int  # Applied patterns unused for 30+ days
    pattern_status_breakdown: dict[str, int]  # Count by status (pending, approved, etc.)


class MemoryStats(BaseModel):
    """Memory system statistics."""

    queue_depth: int
    queue_pending: int
    observations_today: int
    observation_success_rate: float
    token_spend_24h: int
    health: str  # 'healthy', 'degraded', 'unhealthy'
    health_details: dict[str, Any] | None = None
    filtering: FilteringMetrics | None = None
    lifecycle: LifecycleStats | None = None


@router.get("/memory/stats", response_model=MemoryStats)
async def get_memory_stats() -> MemoryStats:
    """Get memory system statistics.

    Returns queue depth, observation counts, success rates, and health status.
    """
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(days=1)

    with get_connection() as conn, conn.cursor() as cur:
        # Queue statistics
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                COUNT(*) FILTER (WHERE status = 'processed'
                    AND processed_at >= %s) as processed_24h,
                COUNT(*) FILTER (WHERE status = 'failed'
                    AND processed_at >= %s) as failed_24h
            FROM observation_queue
            WHERE created_at >= %s
            """,
            (yesterday, yesterday, yesterday),
        )
        queue_row = cur.fetchone()
        pending = queue_row[0] if queue_row else 0
        processing = queue_row[1] if queue_row else 0
        processed_24h = queue_row[2] if queue_row else 0
        failed_24h = queue_row[3] if queue_row else 0

        queue_depth = pending + processing

        # Calculate success rate
        total_completed = processed_24h + failed_24h
        success_rate = (processed_24h / total_completed * 100) if total_completed > 0 else 100.0

        # Observations today
        cur.execute(
            """
            SELECT COUNT(*)
            FROM observations
            WHERE created_at >= %s
            """,
            (today_start,),
        )
        obs_row = cur.fetchone()
        observations_today = obs_row[0] if obs_row else 0

        # Token spend (discovery_tokens from observations in last 24h)
        cur.execute(
            """
            SELECT COALESCE(SUM(discovery_tokens), 0)
            FROM observations
            WHERE created_at >= %s
            """,
            (yesterday,),
        )
        token_row = cur.fetchone()
        token_spend_24h = token_row[0] if token_row else 0

    # Determine health status
    health = "healthy"
    health_details = {}

    if queue_depth > 100:
        health = "degraded"
        health_details["queue_depth"] = f"High queue depth: {queue_depth}"
    if queue_depth > 500:
        health = "unhealthy"
        health_details["queue_depth"] = f"Critical queue depth: {queue_depth}"

    if success_rate < 90:
        if health == "healthy":
            health = "degraded"
        health_details["success_rate"] = f"Low success rate: {success_rate:.1f}%"
    if success_rate < 70:
        health = "unhealthy"
        health_details["success_rate"] = f"Critical success rate: {success_rate:.1f}%"

    # Get filtering metrics from Redis
    filter_metrics = get_filtering_metrics()

    # Get lifecycle stats
    lifecycle_data = memory_storage.get_lifecycle_stats()
    lifecycle = LifecycleStats(
        failed_queue_count=lifecycle_data["failed_queue_count"],
        stuck_queue_count=lifecycle_data["stuck_queue_count"],
        oldest_pending_age_minutes=lifecycle_data["oldest_pending_age_minutes"],
        unreflected_diary_count=lifecycle_data["unreflected_diary_count"],
        stale_patterns_count=lifecycle_data["stale_patterns_count"],
        pattern_status_breakdown=lifecycle_data["pattern_status_breakdown"],
    )

    return MemoryStats(
        queue_depth=queue_depth,
        queue_pending=pending,
        observations_today=observations_today,
        observation_success_rate=round(success_rate, 1),
        token_spend_24h=token_spend_24h,
        health=health,
        health_details=health_details if health_details else None,
        filtering=FilteringMetrics(**filter_metrics),
        lifecycle=lifecycle,
    )


class PaginatedResponse(BaseModel):
    """Generic paginated response with total count."""

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@router.get("/observations", response_model=PaginatedResponse)
async def list_observations_global(
    project_id: str | None = Query(None, description="Filter by project"),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    observation_type: str | None = Query(None, description="Filter by observation type"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List observations across all projects.

    Use project_id query param to filter to a specific project.
    Returns observations sorted by created_at descending (newest first).
    """
    items = memory_storage.list_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/patterns", response_model=PaginatedResponse)
async def list_patterns_global(
    project_id: str | None = Query(None, description="Filter by project"),
    status: str | None = Query(None, description="Filter by status"),
    action: str | None = Query(None, description="Filter by action type"),
    pattern_type: str | None = Query(None, description="Filter by pattern type"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List patterns across all projects.

    Use project_id query param to filter to a specific project.
    Returns patterns sorted by created_at descending (newest first).
    """
    items = memory_storage.list_patterns(
        project_id=project_id,
        status=status,
        action=action,
        pattern_type=pattern_type,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_patterns(
        project_id=project_id,
        status=status,
        action=action,
        pattern_type=pattern_type,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


class BulkPatternRequest(BaseModel):
    """Request body for bulk pattern operations."""

    pattern_ids: list[str]
    reason: str | None = None


class BulkPatternResponse(BaseModel):
    """Response for bulk pattern operations."""

    updated: int
    failed: int
    errors: list[str]


@router.post("/patterns/bulk-approve", response_model=BulkPatternResponse)
async def bulk_approve_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk approve multiple patterns.

    Transitions patterns from 'pending' to 'approved'.
    """
    updated = 0
    failed = 0
    errors = []

    for pattern_id in request.pattern_ids:
        try:
            success = memory_storage.update_pattern_status(
                pattern_id=pattern_id,
                status="approved",
                reviewed_by=request.reason or "bulk-approve",
            )
            if success:
                updated += 1
            else:
                failed += 1
                errors.append(f"Pattern {pattern_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Pattern {pattern_id}: {e!s}")

    return BulkPatternResponse(updated=updated, failed=failed, errors=errors)


@router.post("/patterns/bulk-reject", response_model=BulkPatternResponse)
async def bulk_reject_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk reject multiple patterns.

    Transitions patterns from 'pending' to 'rejected'.
    """
    updated = 0
    failed = 0
    errors = []

    for pattern_id in request.pattern_ids:
        try:
            success = memory_storage.update_pattern_status(
                pattern_id=pattern_id,
                status="rejected",
                reviewed_by=request.reason or "bulk-reject",
            )
            if success:
                updated += 1
            else:
                failed += 1
                errors.append(f"Pattern {pattern_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Pattern {pattern_id}: {e!s}")

    return BulkPatternResponse(updated=updated, failed=failed, errors=errors)


@router.get("/diary", response_model=PaginatedResponse)
async def list_diary_global(
    project_id: str | None = Query(None, description="Filter by project"),
    outcome: str | None = Query(None, description="Filter by outcome"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List diary entries across all projects.

    Use project_id query param to filter to a specific project.
    Returns diary entries sorted by created_at descending (newest first).
    """
    items = memory_storage.list_diary_entries(
        project_id=project_id,
        outcome=outcome,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_diary_entries(
        project_id=project_id,
        outcome=outcome,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


class SearchResult(BaseModel):
    """Unified search result item."""

    entity_type: str  # 'observation', 'pattern', 'user_prompt', 'diary'
    id: str
    title: str | None
    summary: str | None
    score: float
    created_at: str | None
    data: dict[str, Any]


class SearchResponse(BaseModel):
    """Unified search response."""

    query: str
    use_semantic: bool
    total: int
    results: list[SearchResult]


@router.get("/memory/search", response_model=SearchResponse)
async def search_memory(
    q: str = Query(..., min_length=1, description="Search query"),
    project_id: str = Query(..., description="Project ID to search"),
    type: str | None = Query(
        None, description="Filter by type: observation, pattern, user_prompt, diary"
    ),
    concepts: str | None = Query(None, description="Comma-separated concept tags to filter"),
    date_start: str | None = Query(None, description="Filter after date (ISO format)"),
    date_end: str | None = Query(None, description="Filter before date (ISO format)"),
    use_semantic: bool = Query(False, description="Use semantic search (requires embeddings)"),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    """Unified search across observations, patterns, user prompts, and diary.

    If use_semantic is True and embeddings exist, uses vector similarity search.
    Otherwise falls back to full-text search with recency-weighted ranking.

    Returns results with entity type indicators for UI rendering.
    """
    from ..services.memory.embedding_service import EmbeddingService

    results: list[SearchResult] = []
    concept_list = [c.strip() for c in concepts.split(",")] if concepts else None
    _ = date_start, date_end  # TODO: Add date filtering

    # Determine search strategy
    should_use_semantic = use_semantic
    if should_use_semantic:
        # Check if embeddings exist
        has_emb = memory_storage.has_embeddings(project_id)
        if not has_emb:
            should_use_semantic = False

    # Search observations
    if type is None or type == "observation":
        if should_use_semantic:
            # Generate query embedding
            service = EmbeddingService()
            if service.is_available():
                query_embedding = service.embed_text(q)
                obs_results = memory_storage.search_observations_semantic(
                    project_id=project_id,
                    query_embedding=query_embedding,
                    limit=limit,
                )
            else:
                obs_results = memory_storage.search_observations_fts(
                    project_id=project_id,
                    query=q,
                    limit=limit,
                )
        else:
            obs_results = memory_storage.search_observations_fts(
                project_id=project_id,
                query=q,
                limit=limit,
            )

        for obs in obs_results:
            # Filter by concepts if specified
            if concept_list:
                obs_concepts = obs.get("concepts") or []
                if not any(c in obs_concepts for c in concept_list):
                    continue

            results.append(
                SearchResult(
                    entity_type="observation",
                    id=obs["id"],
                    title=obs.get("title"),
                    summary=obs.get("narrative", "")[:200] if obs.get("narrative") else None,
                    score=obs.get("combined_score", obs.get("similarity_score", 0.0)),
                    created_at=obs.get("created_at"),
                    data=obs,
                )
            )

    # Search patterns (FTS only for now)
    if type is None or type == "pattern":
        patterns = memory_storage.list_patterns(
            project_id=project_id,
            limit=limit,
        )
        for pattern in patterns:
            # Simple substring match for patterns
            title = pattern.get("title", "") or ""
            content = pattern.get("content", "") or ""
            if q.lower() in title.lower() or q.lower() in content.lower():
                results.append(
                    SearchResult(
                        entity_type="pattern",
                        id=pattern["id"],
                        title=pattern.get("title"),
                        summary=pattern.get("content", "")[:200]
                        if pattern.get("content")
                        else None,
                        score=0.5,  # Default score for patterns
                        created_at=pattern.get("created_at"),
                        data=pattern,
                    )
                )

    # Search user prompts (if supported)
    if type is None or type == "user_prompt":
        from ..storage import memory_prompts

        prompts = memory_prompts.list_user_prompts(
            project_id=project_id,
            limit=limit,
        )
        for prompt in prompts:
            prompt_text = prompt.get("prompt_text", "") or ""
            if q.lower() in prompt_text.lower():
                results.append(
                    SearchResult(
                        entity_type="user_prompt",
                        id=prompt["id"],
                        title=prompt_text[:100] if prompt_text else None,
                        summary=prompt_text[:200] if prompt_text else None,
                        score=0.5,
                        created_at=prompt.get("created_at"),
                        data=prompt,
                    )
                )

    # Sort by score descending
    results.sort(key=lambda x: x.score, reverse=True)

    # Apply limit
    results = results[:limit]

    return SearchResponse(
        query=q,
        use_semantic=should_use_semantic,
        total=len(results),
        results=results,
    )


# --- Backfill API ---


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


class BackfillRequest(BaseModel):
    """Request body for history backfill."""

    project_id: str
    sessions_limit: int = 10
    dry_run: bool = True


class BackfillResponse(BaseModel):
    """Response from history backfill operation."""

    project_id: str
    sessions_found: int
    sessions_processed: int
    patterns_extracted: int
    observations_created: int
    dry_run: bool
    errors: list[str]
    session_stats: dict[str, Any] | None = None


class BackfillProgress(BaseModel):
    """Progress update for backfill operation."""

    session_index: int
    total_sessions: int
    session_id: str
    patterns_found: int
    errors: list[str]


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


# --- Memory Health API ---


class HealthWarning(BaseModel):
    """A health warning."""

    type: str
    message: str
    severity: str
    details: dict[str, Any] | None = None


class HealthCorrection(BaseModel):
    """A correction that was applied."""

    type: str
    description: str
    details: dict[str, Any] | None = None
    timestamp: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    corrections: list[HealthCorrection]
    warnings: list[HealthWarning]
    metrics: dict[str, Any]
    timestamp: str


@router.get("/memory/health", response_model=HealthResponse)
async def get_memory_health(
    project_id: str = Query(..., description="Project ID to check"),
) -> HealthResponse:
    """Get comprehensive memory health status.

    Returns health metrics including:
    - Filter statistics (received, queued, skipped)
    - Observation distribution by type
    - Pattern status breakdown
    - Embedding coverage
    - Approved patterns waiting to be applied
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    metrics = checker.get_health_metrics()

    return HealthResponse(
        status="healthy",
        corrections=[],
        warnings=[],
        metrics=metrics,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.post("/memory/health/check", response_model=HealthResponse)
async def run_health_check(
    project_id: str = Query(..., description="Project ID to check"),
) -> HealthResponse:
    """Run health check with auto-correction.

    This endpoint:
    1. Checks for approved patterns and applies them
    2. Checks filter rate and adds warnings if too high
    3. Checks for missing observation types
    4. Returns the full report with corrections and warnings
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    report = checker.check_and_correct()

    return HealthResponse(
        status=report.status,
        corrections=[
            HealthCorrection(
                type=c.correction_type,
                description=c.description,
                details=c.details,
                timestamp=c.timestamp,
            )
            for c in report.corrections
        ],
        warnings=[
            HealthWarning(
                type=w.warning_type,
                message=w.message,
                severity=w.severity,
                details=w.details,
            )
            for w in report.warnings
        ],
        metrics=report.metrics,
        timestamp=report.timestamp,
    )
