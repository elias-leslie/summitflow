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
    """Tests for build_rules_index method."""

    def test_scans_global_and_project_directories(self):
        """Scans both ~/.claude/rules/ and project/.claude/rules/."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create project rules directory
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            # Create test rule file
            rule_file = project_rules / "test-rule.md"
            rule_file.write_text("# Test Rule\n\nSome content here.")

            # Mock _get_project_path to return our temp dir
            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                rules_index = builder.build_rules_index()

            # Should have at least the project rule
            project_rules_found = [r for r in rules_index if r["scope"] == "project"]
            assert len(project_rules_found) >= 1

            # Check structure
            test_rule = next((r for r in project_rules_found if "test-rule.md" in r["id"]), None)
            assert test_rule is not None
            assert test_rule["title"] == "Test Rule"
            assert test_rule["t"] == "rule"
            assert test_rule["tok"] > 0

    def test_extracts_title_from_first_heading(self):
        """Extracts title from first # heading in markdown."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            rule_file = project_rules / "my-rule.md"
            rule_file.write_text("# My Custom Rule Title\n\nContent goes here.")

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                rules_index = builder.build_rules_index()

            project_rules_list = [r for r in rules_index if r["scope"] == "project"]
            assert any(r["title"] == "My Custom Rule Title" for r in project_rules_list)

    def test_truncates_long_titles(self):
        """Truncates titles longer than 40 chars."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            long_title = "A" * 50
            rule_file = project_rules / "long-title.md"
            rule_file.write_text(f"# {long_title}\n\nContent.")

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                rules_index = builder.build_rules_index()

            project_rule = next((r for r in rules_index if r["scope"] == "project"), None)
            assert project_rule is not None
            assert len(project_rule["title"]) <= 43  # 40 + "..."
            assert project_rule["title"].endswith("...")

    def test_skips_backup_files(self):
        """Skips .bak files."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            # Create both regular and backup file
            rule_file = project_rules / "rule.md"
            rule_file.write_text("# Rule\n\nContent.")

            backup_file = project_rules / "rule.md.bak"
            backup_file.write_text("# Backup\n\nOld content.")

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                rules_index = builder.build_rules_index()

            project_rules_list = [r for r in rules_index if r["scope"] == "project"]
            # Should have only the regular file, not the backup
            assert len(project_rules_list) == 1
            assert "rule.md" in project_rules_list[0]["id"]
            assert ".bak" not in project_rules_list[0]["id"]

    def test_calculates_token_estimate(self):
        """Calculates token estimate for each rule."""
        from app.services.memory.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            content = "# Rule\n\n" + "x" * 400  # 400 chars + header
            rule_file = project_rules / "rule.md"
            rule_file.write_text(content)

            builder = ContextBuilder(project_id="test")
            with patch.object(builder, "_get_project_path", return_value=Path(tmpdir)):
                rules_index = builder.build_rules_index()

            project_rule = next((r for r in rules_index if r["scope"] == "project"), None)
            assert project_rule is not None
            # ~410 chars / 4 = ~102 tokens
            assert 90 < project_rule["tok"] < 120

    def test_rules_index_scales_reasonably(self):
        """Rules index scales linearly with rule count (~22 tokens per rule)."""
        import json

        from app.services.memory.context_builder import ContextBuilder, estimate_tokens

        with tempfile.TemporaryDirectory() as tmpdir:
            project_rules = Path(tmpdir) / ".claude" / "rules"
            project_rules.mkdir(parents=True)

            # Create 10 rule files (typical project)
            for i in range(10):
                rule_file = project_rules / f"rule-{i}.md"
                rule_file.write_text(f"# Rule {i}\n\nSome content for rule {i}.")

            builder = ContextBuilder(project_id="test")
            # Mock global rules to empty to focus on project rules
            with (
                patch.object(builder, "_get_project_path", return_value=Path(tmpdir)),
                patch("pathlib.Path.home", return_value=Path(tmpdir) / "nonexistent"),
            ):
                rules_index = builder.build_rules_index()

            index_tokens = estimate_tokens(json.dumps(rules_index))
            # ~22 tokens per rule entry (id, t, title, scope, tok)
            # 10 rules = ~220 tokens + overhead
            assert index_tokens < 300, f"Rules index is {index_tokens} tokens, should be < 300"
