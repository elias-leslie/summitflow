"""Unit tests for PatternService."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


class TestApplyPattern:
    """Tests for apply_pattern method."""

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_writes_to_file(self, mock_storage):
        """Apply pattern writes formatted content to rules file."""
        from app.services.memory.pattern_service import PatternService

        # Create temp directory for rules file
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_storage.get_pattern.return_value = {
                "id": "pat-123",
                "title": "Test Pattern",
                "content": "Do this thing.",
                "rationale": "Because reasons.",
                "status": "approved",
                "action": "add",
            }
            mock_storage.mark_pattern_applied.return_value = None

            service = PatternService(project_id="test", project_path=tmpdir)
            service.apply_pattern("pat-123")

            # Check file was created
            rules_path = Path(tmpdir) / ".claude" / "rules" / "learned-patterns.md"
            assert rules_path.exists()

            content = rules_path.read_text()
            assert "## Test Pattern" in content
            assert "Do this thing." in content
            assert "*Rationale: Because reasons.*" in content
            assert "<!-- Pattern ID: pat-123" in content

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_raises_if_not_approved(self, mock_storage):
        """Raises ValueError if pattern is not approved."""
        from app.services.memory.pattern_service import PatternService

        mock_storage.get_pattern.return_value = {
            "id": "pat-123",
            "status": "pending",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            service = PatternService(project_id="test", project_path=tmpdir)
            with pytest.raises(ValueError, match="must be approved"):
                service.apply_pattern("pat-123")


class TestValidateConciseness:
    """Tests for validate_conciseness method."""

    def test_rejects_content_over_500_chars(self):
        """Content over 500 chars is rejected."""
        from app.services.memory.pattern_service import PatternService

        service = PatternService(project_id="test")

        long_content = "x" * 501
        is_valid, violations = service.validate_conciseness("Short title", long_content)

        assert is_valid is False
        assert any("exceeds 500 chars" in v for v in violations)

    def test_rejects_title_over_100_chars(self):
        """Title over 100 chars is rejected."""
        from app.services.memory.pattern_service import PatternService

        service = PatternService(project_id="test")

        long_title = "x" * 101
        is_valid, violations = service.validate_conciseness(long_title, "Short content.")

        assert is_valid is False
        assert any("exceeds 100 chars" in v for v in violations)

    def test_rejects_hedging_words(self):
        """Content with hedging words is rejected."""
        from app.services.memory.pattern_service import PatternService

        service = PatternService(project_id="test")

        hedgy_content = "You might want to do this sometimes."
        is_valid, violations = service.validate_conciseness("Title", hedgy_content)

        assert is_valid is False
        assert any("hedging words" in v for v in violations)

    def test_accepts_valid_content(self):
        """Valid short content passes validation."""
        from app.services.memory.pattern_service import PatternService

        service = PatternService(project_id="test")

        is_valid, violations = service.validate_conciseness(
            "Use semantic tokens",
            "Replace hardcoded colors with semantic design tokens.",
        )

        assert is_valid is True
        assert len(violations) == 0


class TestStatusTransitions:
    """Tests for update_status method."""

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_valid_pending_to_approved(self, mock_storage):
        """Allows pending -> approved transition."""
        from app.services.memory.pattern_service import PatternService

        mock_storage.get_pattern.return_value = {
            "id": "pat-123",
            "status": "pending",
        }
        mock_storage.update_pattern_status.return_value = None

        service = PatternService(project_id="test")
        service.update_status("pat-123", "approved")

        mock_storage.update_pattern_status.assert_called_once()

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_invalid_applied_transition_raises(self, mock_storage):
        """Rejects invalid transition from applied (terminal state)."""
        from app.services.memory.pattern_service import PatternService

        mock_storage.get_pattern.return_value = {
            "id": "pat-123",
            "status": "applied",
        }

        service = PatternService(project_id="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            service.update_status("pat-123", "pending")

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_invalid_pending_to_applied_raises(self, mock_storage):
        """Rejects skipping approved state."""
        from app.services.memory.pattern_service import PatternService

        mock_storage.get_pattern.return_value = {
            "id": "pat-123",
            "status": "pending",
        }

        service = PatternService(project_id="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            service.update_status("pat-123", "applied")


class TestGetStalePatterns:
    """Tests for get_stale_patterns method."""

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_returns_patterns_over_30_days_unused(self, mock_storage):
        """Returns patterns not used in over 30 days."""
        from app.services.memory.pattern_service import PatternService

        old_date = (datetime.now() - timedelta(days=45)).isoformat()
        recent_date = (datetime.now() - timedelta(days=10)).isoformat()

        mock_storage.list_patterns.return_value = [
            {"id": "stale-1", "last_used_at": old_date},
            {"id": "fresh-1", "last_used_at": recent_date},
            {"id": "stale-2", "created_at": old_date, "applied_at": old_date},
        ]

        service = PatternService(project_id="test")
        stale = service.get_stale_patterns(days_threshold=30)

        assert len(stale) == 2
        stale_ids = [p["id"] for p in stale]
        assert "stale-1" in stale_ids
        assert "stale-2" in stale_ids
        assert "fresh-1" not in stale_ids

    @patch("app.services.memory.pattern_service.memory_storage")
    def test_respects_custom_threshold(self, mock_storage):
        """Respects custom days threshold."""
        from app.services.memory.pattern_service import PatternService

        date_20_days = (datetime.now() - timedelta(days=20)).isoformat()
        date_60_days = (datetime.now() - timedelta(days=60)).isoformat()

        mock_storage.list_patterns.return_value = [
            {"id": "pat-20", "last_used_at": date_20_days},
            {"id": "pat-60", "last_used_at": date_60_days},
        ]

        service = PatternService(project_id="test")

        # With 15 day threshold, both should be stale
        stale_15 = service.get_stale_patterns(days_threshold=15)
        assert len(stale_15) == 2

        # With 30 day threshold, only the 60 day one is stale
        stale_30 = service.get_stale_patterns(days_threshold=30)
        assert len(stale_30) == 1
        assert stale_30[0]["id"] == "pat-60"


class TestJsonlFormat:
    """Tests for JSON-lines pattern formatting and parsing."""

    def test_format_pattern_jsonl_index_mode(self):
        """Index mode produces compact output with short ID."""
        from app.services.memory.pattern_service import PatternService

        pattern = {
            "id": "b70160e6-dab8-4a01-bba6-d4f33330be3e",
            "title": "Test Pattern Title",
            "content": "Full content here.",
            "pattern_type": "rule",
            "confidence": 0.85,
        }

        result = PatternService.format_pattern_jsonl(pattern, include_content=False)

        assert '"id":"3330be3e"' in result  # Short ID
        assert '"t":"Test Pattern Title"' in result
        assert '"c":' not in result  # No content in index mode

    def test_format_pattern_jsonl_full_mode(self):
        """Full mode includes content and metadata."""
        from app.services.memory.pattern_service import PatternService

        pattern = {
            "id": "b70160e6-dab8-4a01-bba6-d4f33330be3e",
            "title": "Test Pattern Title",
            "content": "Full content here.",
            "pattern_type": "rule",
            "confidence": 0.85,
        }

        result = PatternService.format_pattern_jsonl(pattern, include_content=True)

        assert '"id":"b70160e6-dab8-4a01-bba6-d4f33330be3e"' in result  # Full ID
        assert '"t":"Test Pattern Title"' in result
        assert '"c":"Full content here."' in result
        assert '"d":"rule"' in result
        assert '"conf":0.85' in result

    def test_parse_pattern_jsonl_index_format(self):
        """Parses index format JSON."""
        from app.services.memory.pattern_service import PatternService

        line = '{"id":"3330be3e","t":"Test Pattern"}'
        result = PatternService.parse_pattern_jsonl(line)

        assert result is not None
        assert result["id"] == "3330be3e"
        assert result["title"] == "Test Pattern"
        assert result["content"] == ""  # Not in index
        assert result["pattern_type"] == "rule"  # Default

    def test_parse_pattern_jsonl_full_format(self):
        """Parses full format JSON."""
        from app.services.memory.pattern_service import PatternService

        line = '{"id":"full-id","t":"Title","c":"Content","d":"preference","conf":0.9}'
        result = PatternService.parse_pattern_jsonl(line)

        assert result is not None
        assert result["id"] == "full-id"
        assert result["title"] == "Title"
        assert result["content"] == "Content"
        assert result["pattern_type"] == "preference"
        assert result["confidence"] == 0.9

    def test_parse_pattern_jsonl_invalid_json(self):
        """Returns None for invalid JSON."""
        from app.services.memory.pattern_service import PatternService

        result = PatternService.parse_pattern_jsonl("not valid json")
        assert result is None


class TestParsePatternFile:
    """Tests for parse_patterns_file with format detection."""

    def test_parse_jsonl_format(self):
        """Detects and parses JSON-lines format."""
        from app.services.memory.pattern_service import PatternService

        content = """{"id":"pat1","t":"Pattern One","c":"Content one.","d":"rule","conf":0.8}
{"id":"pat2","t":"Pattern Two","c":"Content two.","d":"preference","conf":0.9}"""

        patterns = PatternService.parse_patterns_file(content)

        assert len(patterns) == 2
        assert patterns[0]["title"] == "Pattern One"
        assert patterns[1]["title"] == "Pattern Two"

    def test_parse_markdown_format(self):
        """Detects and parses legacy markdown format."""
        from app.services.memory.pattern_service import PatternService

        content = """# Learned Patterns

## First Pattern

Do the first thing correctly.

*Rationale: Because it matters.*

<!-- Pattern ID: abc-123 | Applied: 2026-01-01 -->

## Second Pattern

Do the second thing.

<!-- Pattern ID: def-456 | Applied: 2026-01-02 -->"""

        patterns = PatternService.parse_patterns_file(content)

        assert len(patterns) == 2
        assert patterns[0]["title"] == "First Pattern"
        assert patterns[0]["id"] == "abc-123"
        assert "first thing" in patterns[0]["content"]
        assert patterns[0]["rationale"] == "Because it matters."
        assert patterns[1]["title"] == "Second Pattern"
        assert patterns[1]["id"] == "def-456"

    def test_parse_empty_content(self):
        """Returns empty list for empty content."""
        from app.services.memory.pattern_service import PatternService

        assert PatternService.parse_patterns_file("") == []
        assert PatternService.parse_patterns_file("   \n  ") == []

    def test_roundtrip_jsonl(self):
        """Format then parse produces equivalent pattern."""
        from app.services.memory.pattern_service import PatternService

        original = {
            "id": "test-id-12345678",
            "title": "Roundtrip Test",
            "content": "Test content.",
            "pattern_type": "rule",
            "confidence": 0.75,
        }

        jsonl = PatternService.format_pattern_jsonl(original, include_content=True)
        parsed = PatternService.parse_pattern_jsonl(jsonl)

        assert parsed["id"] == original["id"]
        assert parsed["title"] == original["title"]
        assert parsed["content"] == original["content"]
        assert parsed["confidence"] == original["confidence"]


class TestExpandPatternEntity:
    """Tests for expand_entity with pattern short and full IDs."""

    @patch("app.services.memory.context_builder.get_pattern_by_short_id")
    @patch("app.storage.memory.increment_pattern_usage")
    def test_expand_pattern_by_short_id(self, mock_increment, mock_get_pattern):
        """Expand pattern using short ID (8 chars)."""
        from app.services.memory.context_builder import ContextBuilder

        mock_get_pattern.return_value = {
            "id": "b70160e6-dab8-4a01-bba6-d4f33330be3e",
            "title": "Test Pattern",
            "content": "Do this thing.",
            "pattern_type": "rule",
            "confidence": 0.85,
        }
        mock_increment.return_value = None

        builder = ContextBuilder(project_id="test")
        result = builder.expand_entity("pat:3330be3e")  # Short ID

        assert result["type"] == "pattern"
        assert result["entity_id"] == "pat:b70160e6-dab8-4a01-bba6-d4f33330be3e"
        assert result["content"]["title"] == "Test Pattern"
        assert "jsonl" in result
        assert '"c":"Do this thing."' in result["jsonl"]
        mock_get_pattern.assert_called_once_with("3330be3e")

    @patch("app.services.memory.context_builder.get_pattern_by_short_id")
    @patch("app.storage.memory.increment_pattern_usage")
    def test_expand_pattern_by_full_id(self, mock_increment, mock_get_pattern):
        """Expand pattern using full UUID."""
        from app.services.memory.context_builder import ContextBuilder

        full_id = "b70160e6-dab8-4a01-bba6-d4f33330be3e"
        mock_get_pattern.return_value = {
            "id": full_id,
            "title": "Full ID Pattern",
            "content": "Full content.",
            "pattern_type": "preference",
            "confidence": 0.9,
        }
        mock_increment.return_value = None

        builder = ContextBuilder(project_id="test")
        result = builder.expand_entity(f"pat:{full_id}")

        assert result["type"] == "pattern"
        assert result["entity_id"] == f"pat:{full_id}"
        assert result["content"]["title"] == "Full ID Pattern"
        assert "jsonl" in result
        mock_get_pattern.assert_called_once_with(full_id)

    @patch("app.services.memory.context_builder.get_pattern_by_short_id")
    def test_expand_pattern_not_found(self, mock_get_pattern):
        """Raises KeyError when pattern not found."""
        from app.services.memory.context_builder import ContextBuilder

        mock_get_pattern.return_value = None

        builder = ContextBuilder(project_id="test")
        with pytest.raises(KeyError, match="Pattern not found"):
            builder.expand_entity("pat:nonexist")
