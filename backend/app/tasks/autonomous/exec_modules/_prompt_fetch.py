"""Prompt fetching from Agent Hub through the canonical SDK (``get_prompt``)."""

from __future__ import annotations

from time import sleep

import httpx
from agent_hub.exceptions import AgentHubError, ServerError

from ....logging_config import get_logger
from ....services._agent_hub_config import get_sync_client

logger = get_logger(__name__)

# Prompt cache for process lifetime
_prompt_cache: dict[str, str] = {}
_MAX_FETCH_ATTEMPTS = 3
_FETCH_RETRY_DELAYS = (0.25, 0.5)
_FETCH_TIMEOUT_SECONDS = 5.0


class PromptFetchError(RuntimeError):
    """Prompt fetch failed in a non-recoverable way."""


class TransientPromptFetchError(PromptFetchError):
    """Prompt fetch failed due to temporary Agent Hub unavailability."""


def _fetch_prompt(slug: str) -> dict[str, object]:
    """Fetch one prompt, retrying brief Agent Hub restart windows."""
    with get_sync_client(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        for attempt in range(_MAX_FETCH_ATTEMPTS):
            try:
                return client.get_prompt(slug)
            except (httpx.HTTPError, ServerError) as e:
                if attempt == _MAX_FETCH_ATTEMPTS - 1:
                    raise TransientPromptFetchError(
                        f"Cannot fetch prompt '{slug}' from Agent Hub: {e}"
                    ) from e
                logger.warning(
                    "prompt_fetch_retry", slug=slug, attempt=attempt + 1, error=str(e)
                )
                sleep(_FETCH_RETRY_DELAYS[min(attempt, len(_FETCH_RETRY_DELAYS) - 1)])
            except AgentHubError as e:
                raise PromptFetchError(
                    f"Prompt '{slug}' not found (HTTP {e.status_code}). "
                    f"Seed it with: st prompt create {slug} '<name>' -f <file>"
                ) from e
    raise TransientPromptFetchError(f"Cannot fetch prompt '{slug}' from Agent Hub")


def get_prompt_template(slug: str) -> str:
    """Fetch prompt content from Agent Hub by slug.

    Results are cached for the process lifetime to avoid repeated calls.
    """
    if slug in _prompt_cache:
        return _prompt_cache[slug]

    content = _fetch_prompt(slug).get("content")
    if not isinstance(content, str) or not content:
        raise PromptFetchError(f"Prompt '{slug}' exists but has empty content")

    _prompt_cache[slug] = content
    return content
