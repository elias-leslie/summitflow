"""Graphiti client for Agent Hub memory API integration.

This client provides SummitFlow's self-healing system with access to the
Graphiti knowledge graph for storing and retrieving fix patterns.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, cast

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .._agent_hub_config import (
    SUMMITFLOW_CLIENT_ID,
    SUMMITFLOW_CLIENT_SECRET,
    SUMMITFLOW_REQUEST_SOURCE,
)

logger = logging.getLogger(__name__)

AGENT_HUB_BASE_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8003")
DEFAULT_TIMEOUT = 10.0


@dataclass
class FixPattern:
    """A fix pattern stored in Graphiti."""

    error_signature: str
    fix_diff: str
    root_cause_summary: str
    project_id: str | None = None
    check_type: str | None = None  # ruff, mypy, pytest, etc.


@dataclass
class SearchResult:
    """A search result from Graphiti."""

    pattern: str
    applies_to: str
    example: str | None
    score: float
    metadata: dict[str, Any] | None = None


class GraphitiClient:
    """Client for interacting with Agent Hub's Graphiti memory API."""

    def __init__(self, base_url: str = AGENT_HUB_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        """Initialize the Graphiti client.

        Args:
            base_url: Agent Hub API base URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._auth_headers: dict[str, str] = {}
        if SUMMITFLOW_CLIENT_ID:
            self._auth_headers["X-Client-Id"] = SUMMITFLOW_CLIENT_ID
        if SUMMITFLOW_CLIENT_SECRET:
            self._auth_headers["X-Client-Secret"] = SUMMITFLOW_CLIENT_SECRET
        if SUMMITFLOW_REQUEST_SOURCE:
            self._auth_headers["X-Request-Source"] = SUMMITFLOW_REQUEST_SOURCE

    async def health_check(self) -> dict[str, Any]:
        """Check if the Graphiti API is healthy.

        Returns:
            Health status dict with 'status' and 'neo4j' keys

        Raises:
            httpx.HTTPError: If the health check fails
        """
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._auth_headers) as client:
            response = await client.get(f"{self.base_url}/api/memory/health")
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def store_pattern(
        self,
        pattern: FixPattern,
        scope: str = "project",
    ) -> dict[str, Any]:
        """Store a fix pattern in Graphiti.

        Uses the record-pattern endpoint to store successful fixes
        that can be retrieved for similar errors.

        Args:
            pattern: The fix pattern to store
            scope: Memory scope (global, project, task)

        Returns:
            API response with episode_uuid

        Raises:
            httpx.HTTPError: If the API call fails
        """
        payload = {
            "pattern": f"Fix for {pattern.error_signature}: {pattern.root_cause_summary}",
            "applies_to": f"check_type:{pattern.check_type}" if pattern.check_type else "general",
            "example": pattern.fix_diff[:1000] if pattern.fix_diff else None,
            "scope": scope,
            "scope_id": pattern.project_id,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/memory/record-pattern",
                json=payload,
            )
            response.raise_for_status()
            result = cast(dict[str, Any], response.json())
            logger.info(
                f"Stored fix pattern for {pattern.error_signature}: {result.get('episode_uuid')}"
            )
            return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def search_patterns(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.3,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> list[SearchResult]:
        """Search for relevant fix patterns.

        Args:
            query: Search query (error message, check type, etc.)
            limit: Maximum results to return
            min_score: Minimum relevance score (0-1)
            scope: Memory scope filter
            scope_id: Project/task ID for scoping

        Returns:
            List of search results with patterns
        """
        headers = {}
        if scope:
            headers["x-memory-scope"] = scope
        if scope_id:
            headers["x-scope-id"] = scope_id

        params: dict[str, str | int | float] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/memory/search",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        pattern=item.get("content", ""),
                        applies_to=item.get("applies_to", ""),
                        example=item.get("example"),
                        score=item.get("score", 0.0),
                        metadata=item.get("metadata"),
                    )
                )

            logger.debug(f"Found {len(results)} patterns for query: {query[:50]}")
            return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def record_gotcha(
        self,
        gotcha: str,
        context: str,
        solution: str | None = None,
        scope: str = "project",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a gotcha/pitfall for troubleshooting.

        Args:
            gotcha: Description of the pitfall
            context: Where/when this gotcha applies
            solution: Workaround if known
            scope: Memory scope
            scope_id: Project/task ID

        Returns:
            API response with episode_uuid
        """
        payload = {
            "gotcha": gotcha,
            "context": context,
            "solution": solution,
            "scope": scope,
            "scope_id": scope_id,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/memory/record-gotcha",
                json=payload,
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    async def delete_episode(self, episode_id: str) -> dict[str, Any]:
        """Delete an episode from memory.

        Used for test cleanup - removes the episode and orphaned entities.

        Args:
            episode_id: UUID of the episode to delete

        Returns:
            API response with deletion status
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(
                f"{self.base_url}/api/memory/episode/{episode_id}",
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
