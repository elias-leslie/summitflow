"""Prompt fetching from Agent Hub API."""

from __future__ import annotations

import httpx

from ....logging_config import get_logger
from ....services._agent_hub_config import build_agent_hub_headers

logger = get_logger(__name__)

# Prompt cache for process lifetime
_prompt_cache: dict[str, str] = {}


def get_prompt_template(slug: str) -> str:
    """Fetch prompt content from Agent Hub API by slug.

    Results are cached for the process lifetime to avoid repeated HTTP calls.
    Raises RuntimeError if the prompt cannot be fetched — DB is the sole
    source of truth, there are no hardcoded fallbacks.
    """
    if slug in _prompt_cache:
        return _prompt_cache[slug]

    from ....services.agent_hub_client import (
        AGENT_HUB_URL,
    )

    url = f"{AGENT_HUB_URL}/api/prompts/{slug}"
    headers = build_agent_hub_headers()
    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Cannot fetch prompt '{slug}' from {url}: {e}") from e

    if not response.is_success:
        raise RuntimeError(
            f"Prompt '{slug}' not found (HTTP {response.status_code}). "
            f"Seed it with: st prompt create {slug} '<name>' -f <file>"
        )

    data = response.json()
    content: str = data.get("content", "")
    if not content:
        raise RuntimeError(f"Prompt '{slug}' exists but has empty content")

    _prompt_cache[slug] = content
    return content
