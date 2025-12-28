"""Unit tests for ObservationExtractor."""

from unittest.mock import MagicMock, patch

import pytest


class TestObservationTypes:
    """Tests for observation type validation."""

    def test_observation_types_defined(self):
        """OBSERVATION_TYPES list is defined with expected types."""
        from app.services.memory.observation_extractor import OBSERVATION_TYPES

        expected_types = [
            "pattern",
            "decision",
            "error",
            "constraint",
            "architecture",
            "user_preference",
            "refactoring",
            "operational",
        ]

        assert len(OBSERVATION_TYPES) >= 8
        for t in expected_types:
            assert t in OBSERVATION_TYPES, f"Missing type: {t}"

    @patch("app.services.memory.observation_extractor.ObservationExtractor._get_client")
    @pytest.mark.asyncio
    async def test_extract_returns_valid_type(self, mock_get_client):
        """Extracted observation type must be in OBSERVATION_TYPES."""
        from app.services.memory.observation_extractor import (
            OBSERVATION_TYPES,
            ObservationExtractor,
        )

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = '{"observation_type": "pattern", "title": "Test", "concepts": []}'
        mock_response.model = "test-model"
        mock_response.usage = {"total_tokens": 100}

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Read",
            tool_input={"file_path": "/test.py"},
            tool_output="def hello(): pass",
        )

        assert observation.observation_type in OBSERVATION_TYPES or observation.skipped


class TestHistoryExtractionFocus:
    """Tests for history extraction focus types."""

    def test_history_focus_types_defined(self):
        """HISTORY_EXTRACTION_FOCUS list is defined."""
        from app.services.memory.observation_extractor import HISTORY_EXTRACTION_FOCUS

        expected_focus = [
            "failed_command",
            "user_correction",
            "repeated_failure",
            "successful_recovery",
        ]

        assert len(HISTORY_EXTRACTION_FOCUS) == 4
        for f in expected_focus:
            assert f in HISTORY_EXTRACTION_FOCUS, f"Missing focus: {f}"


class TestMalformedInput:
    """Tests for handling malformed/invalid input."""

    @patch("app.services.memory.observation_extractor.ObservationExtractor._get_client")
    @pytest.mark.asyncio
    async def test_handles_none_input(self, mock_get_client):
        """Doesn't crash when tool_input is None."""
        from app.services.memory.observation_extractor import ObservationExtractor

        mock_response = MagicMock()
        mock_response.content = '{"observation_type": "pattern", "title": "Test", "concepts": []}'
        mock_response.model = "test-model"
        mock_response.usage = {"total_tokens": 100}

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Bash",
            tool_input=None,
            tool_output="command output",
        )

        assert observation is not None
        assert observation.title is not None

    @patch("app.services.memory.observation_extractor.ObservationExtractor._get_client")
    @pytest.mark.asyncio
    async def test_handles_none_output(self, mock_get_client):
        """Doesn't crash when tool_output is None."""
        from app.services.memory.observation_extractor import ObservationExtractor

        mock_response = MagicMock()
        mock_response.content = '{"observation_type": "error", "title": "Test", "concepts": []}'
        mock_response.model = "test-model"
        mock_response.usage = {"total_tokens": 100}

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Write",
            tool_input={"file_path": "/test.py"},
            tool_output=None,
        )

        assert observation is not None

    @patch("app.services.memory.observation_extractor.ObservationExtractor._get_client")
    @pytest.mark.asyncio
    async def test_handles_invalid_json_response(self, mock_get_client):
        """Handles invalid JSON from LLM gracefully."""
        from app.services.memory.observation_extractor import ObservationExtractor

        mock_response = MagicMock()
        mock_response.content = "This is not valid JSON at all { broken"
        mock_response.model = "test-model"
        mock_response.usage = {"total_tokens": 50}

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Read",
            tool_input={"file_path": "/test.py"},
            tool_output="file contents",
        )

        # Should return a valid observation with defaults, not crash
        assert observation is not None
        assert observation.observation_type is not None

    @patch("app.services.memory.observation_extractor.ObservationExtractor._get_client")
    @pytest.mark.asyncio
    async def test_handles_llm_exception(self, mock_get_client):
        """Handles LLM client exception gracefully."""
        from app.services.memory.observation_extractor import ObservationExtractor

        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("LLM API failed")
        mock_get_client.return_value = mock_client

        extractor = ObservationExtractor()
        observation = await extractor.extract(
            tool_name="Edit",
            tool_input={"file_path": "/test.py"},
            tool_output="edited content",
        )

        # Should return error observation, not crash
        assert observation is not None
        assert observation.observation_type == "error"
        assert (
            "failed" in observation.title.lower()
            or "failed" in (observation.narrative or "").lower()
        )


class TestParseJsonResponse:
    """Tests for _parse_json_response helper."""

    def test_parses_valid_json(self):
        """Parses valid JSON string."""
        from app.services.memory.observation_extractor import ObservationExtractor

        extractor = ObservationExtractor()
        result = extractor._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extracts_json_from_markdown(self):
        """Extracts JSON from markdown code block."""
        from app.services.memory.observation_extractor import ObservationExtractor

        extractor = ObservationExtractor()
        content = '```json\n{"key": "value"}\n```'
        result = extractor._parse_json_response(content)
        assert result == {"key": "value"}

    def test_returns_empty_dict_on_failure(self):
        """Returns empty dict when parsing fails."""
        from app.services.memory.observation_extractor import ObservationExtractor

        extractor = ObservationExtractor()
        result = extractor._parse_json_response("not json at all")
        assert result == {}


class TestTruncateOutput:
    """Tests for _truncate_output helper."""

    def test_truncates_long_output(self):
        """Truncates output exceeding max_chars."""
        from app.services.memory.observation_extractor import ObservationExtractor

        extractor = ObservationExtractor()
        long_output = "x" * 5000
        truncated = extractor._truncate_output(long_output, max_chars=2000)

        assert len(truncated) < len(long_output)
        assert "truncated" in truncated

    def test_preserves_short_output(self):
        """Doesn't truncate short output."""
        from app.services.memory.observation_extractor import ObservationExtractor

        extractor = ObservationExtractor()
        short_output = "x" * 100
        result = extractor._truncate_output(short_output, max_chars=2000)

        assert result == short_output
