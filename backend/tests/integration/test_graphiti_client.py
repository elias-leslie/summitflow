"""Integration tests for Graphiti client.

These tests require Agent Hub to be running at localhost:8003.
Graphiti operations can be slow (10-60s) due to Neo4j and LLM calls.
"""

from __future__ import annotations

import pytest

from app.services.self_healing.graphiti_client import FixPattern, GraphitiClient

# Longer timeout for Graphiti operations (LLM + Neo4j can be slow)
GRAPHITI_TIMEOUT = 60.0


@pytest.fixture
def client() -> GraphitiClient:
    """Create a Graphiti client for testing with extended timeout."""
    return GraphitiClient(timeout=GRAPHITI_TIMEOUT)


@pytest.mark.asyncio
async def test_health_check(client: GraphitiClient) -> None:
    """Test that health check returns healthy status."""
    result = await client.health_check()
    assert result["status"] == "healthy"
    assert result["neo4j"] == "connected"


@pytest.mark.asyncio
@pytest.mark.timeout(120)  # Allow up to 2 minutes for Graphiti operations
async def test_store_pattern(client: GraphitiClient) -> None:
    """Test storing a fix pattern.

    This test may be slow (~30-60s) as it involves LLM entity extraction.
    """
    pattern = FixPattern(
        error_signature="ruff:F401:unused import",
        fix_diff="- import unused\n+ # removed unused import",
        root_cause_summary="Removed unused import to fix F401",
        project_id="summitflow",
        check_type="ruff",
    )

    result = await client.store_pattern(pattern)
    assert result["success"] is True
    assert "episode_uuid" in result


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
@pytest.mark.timeout(120)  # Allow up to 2 minutes for Graphiti operations
async def test_record_gotcha(client: GraphitiClient) -> None:
    """Test recording a gotcha.

    This test may be slow (~30-60s) as it involves LLM entity extraction.
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
