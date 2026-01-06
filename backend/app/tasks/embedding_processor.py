"""Celery tasks for batch embedding generation.

Tasks:
- process_pending_embeddings: Generate embeddings for observations and user prompts
"""

from __future__ import annotations

import os
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.memory.embedding_service import EmbeddingService
from ..storage import memory_prompts
from ..storage.memory_embeddings import (
    bulk_update_observation_embeddings,
    get_observations_without_embeddings,
)

logger = get_logger(__name__)

# Global memory system kill switch - checked before processing
MEMORY_SYSTEM_ENABLED = os.getenv("MEMORY_SYSTEM_ENABLED", "true").lower() in ("true", "1", "yes")

# Max items to process in one task execution
BATCH_SIZE = 100


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.process_pending_embeddings",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def process_pending_embeddings(self: Any, limit: int = BATCH_SIZE) -> dict[str, Any]:
    """Process pending items that need embeddings.

    Fetches observations and user prompts without embeddings,
    generates embeddings in batches, and updates the records.

    Args:
        limit: Max items to process in this run

    Returns:
        Summary dict with processed counts
    """
    # Global kill switch - memory system disabled pending migration
    if not MEMORY_SYSTEM_ENABLED:
        logger.debug("embedding_processing_skipped: memory system disabled")
        return {
            "status": "skipped",
            "reason": "memory_system_disabled",
            "observations_processed": 0,
            "prompts_processed": 0,
        }

    logger.info("embedding_processing_started", limit=limit)

    # Initialize embedding service
    service = EmbeddingService()
    if not service.is_available():
        logger.warning("embedding_service_unavailable")
        return {
            "status": "skipped",
            "reason": "embedding_service_unavailable",
            "observations_processed": 0,
            "prompts_processed": 0,
        }

    observations_processed = 0
    prompts_processed = 0

    # Process observations
    observations_processed = _process_observation_embeddings(service, limit)

    # Process user prompts
    prompts_processed = _process_prompt_embeddings(service, limit)

    logger.info(
        "embedding_processing_completed",
        observations=observations_processed,
        prompts=prompts_processed,
    )

    return {
        "status": "completed",
        "observations_processed": observations_processed,
        "prompts_processed": prompts_processed,
    }


def _process_observation_embeddings(service: EmbeddingService, limit: int) -> int:
    """Process embeddings for observations.

    Generates separate embeddings for narrative and title.

    Args:
        service: Initialized EmbeddingService
        limit: Max observations to process

    Returns:
        Number of observations processed
    """
    # Get observations without embeddings
    observations = get_observations_without_embeddings(limit=limit)

    if not observations:
        logger.debug("no_observations_need_embeddings")
        return 0

    logger.info(f"processing_observation_embeddings: {len(observations)} observations")

    # Extract texts for batch embedding
    narratives = [obs["narrative"] for obs in observations]
    titles = [obs["title"] for obs in observations]

    # Generate embeddings in 2 batch calls (narratives and titles)
    narrative_embeddings = service.embed_batch(narratives)
    title_embeddings = service.embed_batch(titles)

    # Prepare updates
    updates: list[tuple[str, list[float], list[float]]] = []
    for i, obs in enumerate(observations):
        updates.append((obs["id"], narrative_embeddings[i], title_embeddings[i]))

    # Bulk update
    updated = bulk_update_observation_embeddings(updates)

    logger.info(f"observation_embeddings_updated: {updated}")
    return updated


def _process_prompt_embeddings(service: EmbeddingService, limit: int) -> int:
    """Process embeddings for user prompts.

    Args:
        service: Initialized EmbeddingService
        limit: Max prompts to process

    Returns:
        Number of prompts processed
    """
    # Get prompts without embeddings
    prompts = memory_prompts.get_prompts_without_embeddings(limit=limit)

    if not prompts:
        logger.debug("no_prompts_need_embeddings")
        return 0

    logger.info(f"processing_prompt_embeddings: {len(prompts)} prompts")

    # Extract texts for batch embedding
    texts = [p["prompt_text"] for p in prompts]

    # Generate embeddings in one batch call
    embeddings = service.embed_batch(texts)

    # Prepare updates
    updates: list[tuple[str, list[float]]] = []
    for i, prompt in enumerate(prompts):
        updates.append((prompt["id"], embeddings[i]))

    # Bulk update
    updated = memory_prompts.bulk_update_prompt_embeddings(updates)

    logger.info(f"prompt_embeddings_updated: {updated}")
    return updated
