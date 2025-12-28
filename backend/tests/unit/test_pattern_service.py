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
