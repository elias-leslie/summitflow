"""Memory Search API - Unified search across memory entities.

Endpoints:
- GET /memory/search - Unified search across observations, patterns, user prompts, and diary
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..storage import memory as memory_storage
from .memory_models import SearchResponse, SearchResult

router = APIRouter()


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

    # Search patterns (FTS only for now) - only search applied patterns
    if type is None or type == "pattern":
        patterns = memory_storage.list_patterns(
            project_id=project_id,
            status="applied",
            limit=limit,
        )
        for pattern in patterns:
            # Simple substring match for patterns
            title = pattern.get("title", "") or ""
            content = pattern.get("content", "") or ""
            if q.lower() in title.lower() or q.lower() in content.lower():
                # Score patterns higher - they're curated knowledge
                # Base: 0.8, usage boost: +0.05 per use (max +0.15), confidence factor
                base_score = 0.8
                usage_boost = min(0.15, pattern.get("usage_count", 0) * 0.05)
                confidence = pattern.get("confidence", 1.0)
                score = min(0.95, (base_score + usage_boost) * confidence)

                results.append(
                    SearchResult(
                        entity_type="pattern",
                        id=pattern["id"],
                        title=pattern.get("title"),
                        summary=pattern.get("content", "")[:200]
                        if pattern.get("content")
                        else None,
                        score=round(score, 2),
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
