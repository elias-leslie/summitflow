"""Prompt fetching from Agent Hub API."""

from __future__ import annotations

from time import sleep

import httpx

from ....logging_config import get_logger
from ....services._agent_hub_config import build_agent_hub_headers

logger = get_logger(__name__)

# Prompt cache for process lifetime
_prompt_cache: dict[str, str] = {}
_MAX_FETCH_ATTEMPTS = 3
_FETCH_RETRY_DELAYS = (0.25, 0.5)


class PromptFetchError(RuntimeError):
    """Prompt fetch failed in a non-recoverable way."""


class TransientPromptFetchError(PromptFetchError):
    """Prompt fetch failed due to temporary Agent Hub unavailability."""


def get_prompt_template(slug: str) -> str:
    """Fetch prompt content from Agent Hub API by slug.

    Results are cached for the process lifetime to avoid repeated HTTP calls.
    Retries transient service failures caused by brief Agent Hub restart windows.
    """
    if slug in _prompt_cache:
        return _prompt_cache[slug]

    from ....services.agent_hub_client import (
        AGENT_HUB_URL,
    )

    url = f"{AGENT_HUB_URL}/api/prompts/{slug}"
    headers = build_agent_hub_headers()
    last_error: Exception | None = None
    for attempt in range(_MAX_FETCH_ATTEMPTS):
        try:
            response = httpx.get(url, headers=headers, timeout=5.0)
        except httpx.HTTPError as e:
            last_error = e
            if attempt == _MAX_FETCH_ATTEMPTS - 1:
                raise TransientPromptFetchError(
                    f"Cannot fetch prompt '{slug}' from {url}: {e}"
                ) from e
            logger.warning(
                "prompt_fetch_retry",
                slug=slug,
                url=url,
                attempt=attempt + 1,
                error=str(e),
            )
            sleep(_FETCH_RETRY_DELAYS[min(attempt, len(_FETCH_RETRY_DELAYS) - 1)])
            continue

        if response.is_success:
            break

        if response.status_code >= 500:
            last_error = RuntimeError(f"HTTP {response.status_code}")
            if attempt == _MAX_FETCH_ATTEMPTS - 1:
                raise TransientPromptFetchError(
                    f"Cannot fetch prompt '{slug}' from {url}: HTTP {response.status_code}"
                )
            logger.warning(
                "prompt_fetch_retry",
                slug=slug,
                url=url,
                attempt=attempt + 1,
                status_code=response.status_code,
            )
            sleep(_FETCH_RETRY_DELAYS[min(attempt, len(_FETCH_RETRY_DELAYS) - 1)])
            continue

        raise PromptFetchError(
            f"Prompt '{slug}' not found (HTTP {response.status_code}). "
            f"Seed it with: st prompt create {slug} '<name>' -f <file>"
        )
    else:
        raise TransientPromptFetchError(
            f"Cannot fetch prompt '{slug}' from {url}: {last_error or 'unknown error'}"
        )

    data = response.json()
    content: str = data.get("content", "")
    if not content:
        raise PromptFetchError(f"Prompt '{slug}' exists but has empty content")

    _prompt_cache[slug] = content
    return content
