"""Unit tests for pattern memory service.

Tests pattern formatting, signature computation, and mock API interactions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.self_healing.graphiti_client import SearchResult
from app.services.self_healing.pattern_memory import (
    PatternMemoryService,
    compute_error_signature,
)


class TestComputeErrorSignature:
    """Tests for error signature computation."""

    def test_signature_is_stable(self) -> None:
        """Same input produces same signature."""
        sig1 = compute_error_signature("ruff", "F401", "'os' imported but unused")
        sig2 = compute_error_signature("ruff", "F401", "'os' imported but unused")
        assert sig1 == sig2

    def test_different_errors_different_signatures(self) -> None:
        """Different errors produce different signatures."""
        sig1 = compute_error_signature("ruff", "F401", "'os' imported but unused")
        sig2 = compute_error_signature("ruff", "F401", "'sys' imported but unused")
        assert sig1 != sig2

    def test_signature_length(self) -> None:
        """Signature is truncated to 16 characters."""
        sig = compute_error_signature("ruff", "F401", "test error")
        assert len(sig) == 16

    def test_signature_case_insensitive(self) -> None:
        """Signature is case insensitive for error message."""
        sig1 = compute_error_signature("ruff", "F401", "Error Message")
        sig2 = compute_error_signature("ruff", "F401", "error message")
        assert sig1 == sig2


class TestPatternMemoryService:
    """Tests for PatternMemoryService."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock GraphitiClient."""
        client = MagicMock()
        client.store_pattern = AsyncMock(
            return_value={"success": True, "episode_uuid": "test-uuid"}
        )
        client.search_patterns = AsyncMock(return_value=[])
        client.record_gotcha = AsyncMock(
            return_value={"success": True, "episode_uuid": "gotcha-uuid"}
        )
        return client

    @pytest.fixture
    def service(self, mock_client: MagicMock) -> PatternMemoryService:
        """Create a PatternMemoryService with mock client."""
        return PatternMemoryService(client=mock_client, project_id="test-project")

    @pytest.mark.asyncio
    async def test_store_fix_pattern(
        self, service: PatternMemoryService, mock_client: MagicMock
    ) -> None:
        """Test storing a fix pattern."""
        result = await service.store_fix_pattern(
            check_type="ruff",
            error_code="F401",
            error_message="'os' imported but unused",
            file_path="test.py",
            fix_diff="- import os",
            root_cause_summary="Removed unused import",
        )

        assert result["success"] is True
        assert "episode_uuid" in result

        # Verify client was called with correct arguments
        mock_client.store_pattern.assert_called_once()
        call_args = mock_client.store_pattern.call_args
        pattern = call_args[0][0]
        assert "ruff:F401:" in pattern.error_signature
        assert pattern.fix_diff == "- import os"
        assert pattern.check_type == "ruff"

    @pytest.mark.asyncio
    async def test_get_similar_patterns_empty(
        self, service: PatternMemoryService, mock_client: MagicMock
    ) -> None:
        """Test getting similar patterns when none exist."""
        patterns = await service.get_similar_patterns(
            check_type="ruff",
            error_code="F401",
            error_message="test error",
        )

        assert patterns == []
        mock_client.search_patterns.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_similar_patterns_with_results(
        self, service: PatternMemoryService, mock_client: MagicMock
    ) -> None:
        """Test getting similar patterns with results."""
        mock_client.search_patterns.return_value = [
            SearchResult(
                pattern="Fix for ruff:F401: Removed unused import",
                applies_to="check_type:ruff",
                example="- import unused",
                score=0.85,
                metadata=None,
            )
        ]

        patterns = await service.get_similar_patterns(
            check_type="ruff",
            error_code="F401",
            error_message="test error",
        )

        assert len(patterns) == 1
        assert patterns[0].error_type == "ruff"
        assert patterns[0].similarity_score == 0.85
        assert patterns[0].fix_diff == "- import unused"

    @pytest.mark.asyncio
    async def test_record_gotcha(
        self, service: PatternMemoryService, mock_client: MagicMock
    ) -> None:
        """Test recording a gotcha."""
        result = await service.record_gotcha(
            check_type="mypy",
            gotcha="Type ignore comments can mask real errors",
            context="When fixing type errors",
            solution="Review all type: ignore comments",
        )

        assert result["success"] is True
        mock_client.record_gotcha.assert_called_once()

        call_args = mock_client.record_gotcha.call_args
        assert call_args[1]["context"] == "mypy: When fixing type errors"
        assert call_args[1]["scope"] == "project"

    def test_parse_search_result_valid(
        self, service: PatternMemoryService
    ) -> None:
        """Test parsing a valid search result."""
        result = SearchResult(
            pattern="Fix for ruff:F401:abc123: Removed unused import os",
            applies_to="check_type:ruff",
            example="- import os\n+ # removed",
            score=0.9,
            metadata=None,
        )

        parsed = service._parse_search_result(result)

        assert parsed is not None
        assert parsed.error_type == "ruff"
        assert parsed.similarity_score == 0.9
        assert "import os" in parsed.fix_diff

    def test_parse_search_result_malformed(
        self, service: PatternMemoryService
    ) -> None:
        """Test parsing handles malformed results gracefully."""
        result = SearchResult(
            pattern="Some random text without expected format",
            applies_to="",
            example=None,
            score=0.5,
            metadata=None,
        )

        parsed = service._parse_search_result(result)

        # Should still return something, not crash
        assert parsed is not None
        assert parsed.error_type == "unknown"
