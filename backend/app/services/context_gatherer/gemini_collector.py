"""Gemini context collector."""

from __future__ import annotations

import hashlib
import logging
import time

from ...storage.projects import get_project_root_path
from .token_utils import MAX_GEMINI_TOKENS, truncate_to_tokens

logger = logging.getLogger(__name__)

# Simple in-memory cache for Gemini responses (keyed by project_id + query hash)
_gemini_cache: dict[str, tuple[str, float]] = {}
GEMINI_CACHE_TTL = 3600  # 1 hour


def gather_gemini_context(project_id: str, query: str) -> str:
    """Use Gemini 1M context for deep codebase search.

    Uses Gemini to search through project files and provide relevant context
    based on the user's query. Results are cached to avoid excessive API calls.

    Args:
        project_id: Project ID
        query: Search query / task description

    Returns:
        Gemini's analysis of relevant code as string, or empty string on failure.
    """
    # Check cache first
    cache_key = f"{project_id}:{hashlib.md5(query.encode()).hexdigest()[:16]}"
    if cache_key in _gemini_cache:
        cached_result, cached_time = _gemini_cache[cache_key]
        if time.time() - cached_time < GEMINI_CACHE_TTL:
            logger.debug("Using cached Gemini context for %s", project_id)
            return cached_result

    root_path = get_project_root_path(project_id)
    if not root_path:
        return ""

    try:
        from ...services.agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="analyst")
        if not client.is_available():
            logger.warning("Gemini not available for context gathering")
            return ""

        # Build prompt for codebase analysis
        prompt = f"""You are a helpful assistant analyzing a codebase to help enrich a task.

Project root: {root_path}

User's task request:
{query}

Based on this request, identify:
1. Which files/modules are likely relevant
2. Existing patterns that should be followed
3. Any dependencies or integrations to consider
4. Potential challenges or edge cases

Be concise - focus on the most important context for implementing this task.
Limit your response to ~500 words."""

        response = client.generate(prompt, temperature=0.3, purpose="context_gathering")
        result = response.content

        # Cache the result
        _gemini_cache[cache_key] = (result, time.time())

        return truncate_to_tokens(result, MAX_GEMINI_TOKENS)
    except Exception as e:
        logger.warning("Failed to get Gemini context for %s: %s", project_id, e)
        return ""
