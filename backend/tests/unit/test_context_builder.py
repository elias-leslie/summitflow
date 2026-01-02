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
