"""Feedback for Agent Hub memories cited by the autonomous pipeline."""

from __future__ import annotations

import contextlib

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client

logger = get_logger(__name__)

def rate_cited_memories(
    cited_uuids: list[str],
    rating: str = "helpful",
) -> None:
    """Rate cited memory episodes after successful task completion."""
    if not cited_uuids:
        return
    try:
        client = get_sync_client()
        for uuid in cited_uuids[:10]:  # Cap to avoid excessive API calls
            with contextlib.suppress(Exception):
                client.rate_episode(uuid, rating)
    except Exception as e:
        logger.debug("Memory rating failed (non-blocking)", error=str(e))
