"""Unit tests for ContextBuilder."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestExpandDocSection:
    """Tests for doc: prefix expansion with section support."""

    def test_expand_full_doc(self):
        """Expands full doc when no section specified."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            doc_file = Path(tmpdir) / "TEST.md"
            doc_file.write_text("# Test Doc\n\nSome content here.")

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                result = builder.expand_entity("doc:TEST.md")

            assert result["type"] == "doc"
            assert "# Test Doc" in result["content"]["content"]
            assert result["content"]["section"] is None

    def test_expand_doc_section(self):
        """Expands specific section when section slug specified."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            doc_file = Path(tmpdir) / "TEST.md"
            doc_file.write_text(
                "# Test Doc\n\n"
                "## Quick Reference\n\nThis is quick ref.\n\n"
                "## Services\n\nThis is services.\n\n"
                "## URLs\n\nThese are urls.\n"
            )

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                result = builder.expand_entity("doc:TEST.md#services")

            assert result["type"] == "doc"
            assert result["content"]["section"] == "services"
            assert "## Services" in result["content"]["content"]
            assert "This is services." in result["content"]["content"]
            # Should NOT include content from other sections
            assert "Quick Reference" not in result["content"]["content"]
            assert "URLs" not in result["content"]["content"]

    def test_section_slug_normalization(self):
        """Slugs are normalized (lowercase, dashes)."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            doc_file = Path(tmpdir) / "TEST.md"
            doc_file.write_text(
                "# Doc\n\n"
                "## My Custom Section Title\n\nContent here.\n\n"
                "## Another Section\n\nOther content.\n"
            )

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                result = builder.expand_entity("doc:TEST.md#my-custom-section-title")

            assert "## My Custom Section Title" in result["content"]["content"]
            assert "Content here." in result["content"]["content"]

    def test_section_not_found_raises_key_error(self):
        """Raises KeyError when section not found."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            doc_file = Path(tmpdir) / "TEST.md"
            doc_file.write_text("# Doc\n\n## Only Section\n\nContent.")

            builder = ContextBuilder(project_id="test")
            with (
                patch.object(builder, "_get_project_path", return_value=Path(tmpdir)),
                pytest.raises(KeyError, match="Section not found"),
            ):
                builder.expand_entity("doc:TEST.md#nonexistent-section")


class TestAccessLogging:
    """Tests for context access logging during expansion."""

    def test_logs_access_on_observation_expand(self):
        """Logs access when observation is expanded with session_id."""

        from app.services.memory.context_builder import ContextBuilder

        # Mock observation
        mock_obs = {
            "id": "test-obs-123",
            "project_id": "test",
            "session_id": "session-abc",
            "agent_type": "test",
            "observation_type": "operational",
            "title": "Test observation",
            "narrative": "Test narrative",
            "concepts": [],
            "priority": "medium",
            "confidence": 0.8,
            "entities": [],
            "subtitle": None,
            "facts": None,
            "files_read": [],
            "files_modified": [],
            "tool_name": None,
            "tool_input": None,
            "discovery_tokens": 0,
            "extracted_by": None,
            "raw_excerpt": None,
            "created_at": "2026-01-02T10:00:00Z",
        }

        with (
            patch("app.storage.memory.get_observation", return_value=mock_obs),
            patch("app.storage.context_access.log_context_access") as mock_log,
        ):
            builder = ContextBuilder(
                project_id="test",
                session_id="session-abc",
                access_source="api",
                task_id="task-123",
            )
            result = builder.expand_entity("obs:test-obs-123")

            # Verify access was logged
            mock_log.assert_called_once_with(
                project_id="test",
                session_id="session-abc",
                entity_type="observation",
                entity_id="test-obs-123",
                access_source="api",
                task_id="task-123",
            )
            assert result["type"] == "observation"

    def test_skips_logging_when_no_session(self):
        """Does not log when session_id is None."""
        from app.services.memory.context_builder import ContextBuilder

        mock_obs = {
            "id": "test-obs-123",
            "project_id": "test",
            "session_id": "session-abc",
            "agent_type": "test",
            "observation_type": "operational",
            "title": "Test observation",
            "narrative": "Test narrative",
            "concepts": [],
            "priority": "medium",
            "confidence": 0.8,
            "entities": [],
            "subtitle": None,
            "facts": None,
            "files_read": [],
            "files_modified": [],
            "tool_name": None,
            "tool_input": None,
            "discovery_tokens": 0,
            "extracted_by": None,
            "raw_excerpt": None,
            "created_at": "2026-01-02T10:00:00Z",
        }

        with (
            patch("app.storage.memory.get_observation", return_value=mock_obs),
            patch("app.storage.context_access.log_context_access") as mock_log,
        ):
            builder = ContextBuilder(
                project_id="test",
                session_id=None,  # No session
                access_source="api",
            )
            result = builder.expand_entity("obs:test-obs-123")

            # Verify access was NOT logged
            mock_log.assert_not_called()
            assert result["type"] == "observation"


class TestBuildRulesIndex:
    """Tests for build_rules_index method.

    NOTE: build_rules_index was deprecated 2026-01-02 when rules were
    consolidated into CLAUDE.md. These tests verify the deprecation behavior.
    """

    def test_returns_empty_list(self):
        """Returns empty list after rules consolidation."""
        from app.services.memory.context_builder import ContextBuilder

        builder = ContextBuilder(project_id="test")
        rules_index = builder.build_rules_index()

        assert rules_index == []
        assert isinstance(rules_index, list)
