"""Integration tests for Graphiti client.

These tests require Agent Hub to be running at localhost:8003.
Graphiti operations can be slow (30-120s) due to Neo4j and LLM calls.

Tests create episodes and clean them up afterwards to avoid polluting the graph.

Run with: dt pytest -- -m slow backend/tests/integration/test_graphiti_client.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.services.self_healing.graphiti_client import FixPattern, GraphitiClient

# Mark all tests in this module as slow (skipped by default)
pytestmark = [pytest.mark.slow, pytest.mark.integration]

# Extended timeout for Graphiti operations - LLM entity extraction can take 30-90s
GRAPHITI_TIMEOUT = 120.0


@pytest.fixture
def client() -> GraphitiClient:
    """Create a Graphiti client for testing with extended timeout."""
    return GraphitiClient(timeout=GRAPHITI_TIMEOUT)


@pytest.fixture
async def cleanup_episodes(client: GraphitiClient) -> AsyncIterator[list[str]]:
    """Fixture to track and clean up created episodes after test.

    Usage:
        async def test_something(client, cleanup_episodes):
            result = await client.store_pattern(...)
            cleanup_episodes.append(result["episode_uuid"])
    """
    episode_ids: list[str] = []
    yield episode_ids

    # Cleanup all created episodes after test
    for episode_id in episode_ids:
        try:
            await client.delete_episode(episode_id)
        except Exception:
            # Ignore cleanup errors - episode may not exist
            pass


@pytest.mark.asyncio
async def test_health_check(client: GraphitiClient) -> None:
    """Test that health check returns healthy status."""
    result = await client.health_check()
    assert result["status"] == "healthy"
    assert result["neo4j"] == "connected"


@pytest.mark.asyncio
@pytest.mark.timeout(180)  # 3 minutes for Graphiti LLM operations
async def test_store_pattern(client: GraphitiClient, cleanup_episodes: list[str]) -> None:
    """Test storing a fix pattern.

    This test may be slow (~30-90s) as it involves LLM entity extraction.
    """
    pattern = FixPattern(
        error_signature="ruff:F401:unused import",
        fix_diff="- import unused\n+ # removed unused import",
        root_cause_summary="Removed unused import to fix F401",
        project_id="test-project",
        check_type="ruff",
    )

    result = await client.store_pattern(pattern)
    assert result["success"] is True
    assert "episode_uuid" in result

    # Track for cleanup
    cleanup_episodes.append(result["episode_uuid"])


@pytest.mark.asyncio
async def test_search_patterns(client: GraphitiClient) -> None:
    """Test searching for patterns.

    Note: Results may be empty if no patterns have been indexed yet.
    The test verifies the API call succeeds and returns the expected structure.
    """
    results = await client.search_patterns("ruff lint error", limit=5)
    assert isinstance(results, list)
    # Results may be empty, but API should return successfully


@pytest.mark.asyncio
@pytest.mark.timeout(180)  # 3 minutes for Graphiti LLM operations
async def test_record_gotcha(client: GraphitiClient, cleanup_episodes: list[str]) -> None:
    """Test recording a gotcha.

    This test may be slow (~30-90s) as it involves LLM entity extraction.
    """
    result = await client.record_gotcha(
        gotcha="GraphitiClient requires httpx async",
        context="self-healing integration",
        solution="Use httpx.AsyncClient with async/await",
        scope="project",
        scope_id="summitflow",
    )
    assert result["success"] is True
    assert "episode_uuid" in result

    # Track for cleanup
    cleanup_episodes.append(result["episode_uuid"])
